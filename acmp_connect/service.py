"""Account-scoped operations and at-most-once upload orchestration."""
import hashlib
import json
import re
import time
from .acmp_client import ACMPClient, positive, MAX_SOURCE
from .client import ACMPError, authenticated_user, language


class Service:
    def __init__(self, storage, settings, client_factory=ACMPClient):
        self.storage, self.settings, self.client_factory = storage, settings, client_factory

    def client(self, subject):
        user, cookies = self.storage.account(subject)
        client = self.client_factory()
        client.load_cookies(cookies)
        if client.identity() != user:
            raise ACMPError('ACMP session identity changed. Reconnect your account.')
        return user, client

    def connect(self, subject, login, password):
        self.storage.rate('login:' + subject, maximum=5, window=300)
        if not login or not password or len(login) > 128 or len(password) > 512:
            raise ACMPError('Invalid credentials length.')
        client = self.client_factory()
        user, _ = client.login(login, password, 1)
        self.storage.save_account(subject, user, client.dump_cookies(), self.settings.session_ttl)
        return user

    def account_status(self, subject):
        try:
            user, _ = self.storage.account(subject)
        except ACMPError:
            return {'connected': False, 'connection_url': self.settings.public_url + '/connect'}
        try:
            self.client(subject)
            return {'connected': True, 'acmp_user_id': user, 'connection_url': self.settings.public_url + '/connect'}
        except ACMPError as exc:
            return {'connected': False, 'message': str(exc), 'connection_url': self.settings.public_url + '/connect'}

    def submit(self, subject, task, lang, source, key):
        positive(task)
        if lang not in {'C', 'C++'}:
            raise ACMPError('Language must be C or C++.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key):
            raise ACMPError('Use a unique 16..128 character idempotency key for each explicit user submission.')
        if not source.strip() or len(source) > MAX_SOURCE or '\0' in source:
            raise ACMPError('Source must contain 1..131072 characters and no NUL bytes.')
        try:
            encoded = source.encode('windows-1251')
        except UnicodeError:
            raise ACMPError('Source contains characters unsupported by ACMP Windows-1251.') from None
        fingerprint = hashlib.sha256(json.dumps([task, lang, source], ensure_ascii=True).encode()).hexdigest()
        # Return a durable replay before opening any network connection.
        existing = self.storage.operation(subject, key)
        if existing:
            if existing['fingerprint'] != fingerprint:
                raise ACMPError('Idempotency key was already used with different input.')
            return json.loads(existing['result'])
        user, client = self.client(subject)
        page = client.request(f'/index.asp?main=task&id_task={task}')
        if authenticated_user(page) != user:
            raise ACMPError('ACMP session expired.')
        compiler_fallback = False
        try:
            compiler = language(page, '.c' if lang == 'C' else '.cpp')
        except ACMPError:
            if lang != 'C':
                raise
            compiler = language(page, '.c', allow_cpp_fallback=True)
            compiler_fallback = True
        before = max((r['id'] for r in client.submissions(user, task)), default=0)
        replay = self.storage.reserve(subject, key, user, fingerprint, task, self.settings.submission_interval)
        if replay is not None:
            return replay
        result = {'operation_key': key, 'state': 'uncertain', 'id': None, 'task': task,
                  'baseline_id': before, 'compiler': compiler, 'compiler_id': compiler,
                  'requested_language': lang, 'compiler_language': 'C++' if compiler_fallback else lang,
                  'compiler_fallback': compiler_fallback,
                  'message': 'Upload may have been received. Check submissions; never automatically resubmit.'}
        if compiler_fallback:
            result['compiler_warning'] = (
                'C source is sent unchanged to a GNU C++ compiler for judging; '
                'only C/C++-compatible constructs are supported.')
        # Store the baseline BEFORE POST so a crash remains reconcilable.
        self.storage.finish(subject, key, {**result, 'state': 'reserved'})
        try:
            reply = client.upload(task, compiler, encoded)  # exactly one POST; no retry
            new = [r for r in client.submissions(user, task) if r['id'] > before]
            if len(new) == 1 and client.matches_source(new[0]['id'], encoded):
                result = {**result, **new[0], 'state': 'submitted', 'verdict_state': new[0]['state'],
                          'message': 'Submission confirmed by ACMP. Query get_verdict for its current verdict.'}
            elif len(new) > 1:
                result['message'] = 'Multiple new submissions; cannot attribute automatically. Reconcile explicitly.'
            elif len(new) == 1:
                result['message'] = 'New row found, but its stored source could not be matched. Reconcile explicitly; no retry performed.'
            else:
                # A rejection is certain only when the site positively says so.
                from .client import text
                message = text(reply)
                if re.search(r'слишком часто|подождите|too frequent|rate limit', message, re.I):
                    result.update(state='rejected', message='ACMP reported a rate limit. No retry performed.')
        except ACMPError:
            pass  # Any failure after POST starts is ambiguous; preserve reservation.
        except Exception:
            self.storage.finish(subject, key, result)
            raise
        self.storage.finish(subject, key, result)
        return result

    def recent(self, subject, limit=20):
        user, client = self.client(subject)
        return {'submissions': client.submissions(user)[:limit]}

    def verdict(self, subject, identifier, wait_seconds=0):
        positive(identifier)
        user, client = self.client(subject)
        deadline = time.monotonic() + min(max(wait_seconds, 0), 20)
        while True:
            rows = client.submissions(user, submission_id=identifier)
            row = next((r for r in rows if r['id'] == identifier and r['user'] == user), None)
            for page_index in range(1, 5):
                if row or not rows or min(r['id'] for r in rows) < identifier:
                    break
                rows = client.submissions(user, submission_id=identifier, page_index=page_index)
                row = next((r for r in rows if r['id'] == identifier and r['user'] == user), None)
            if row is None:
                raise ACMPError('Submission not found in your account or outside the ACMP status window. No other account is queried.')
            if row['state'] != 'pending' or time.monotonic() >= deadline:
                if row['verdict'] == 'Compilation error':
                    try:
                        row = {**row, 'compiler_log': client.diagnostics(identifier)}
                    except ACMPError:
                        row = {**row, 'compiler_log': None}
                return {**row, 'wait_timed_out': row['state'] == 'pending' and wait_seconds > 0}
            time.sleep(min(2, max(0, deadline - time.monotonic())))

    def reconcile(self, subject, key, identifier):
        operation = self.storage.operation(subject, key)
        if not operation:
            raise ACMPError('Operation not found in your account.')
        previous = json.loads(operation['result'])
        if operation['state'] not in {'uncertain'}:
            return previous
        row = self.verdict(subject, identifier)
        if row['task'] != operation['task'] or row['id'] <= previous.get('baseline_id', 2**63):
            raise ACMPError('Submission does not match this operation task and baseline.')
        result = {**previous, **row, 'state': 'submitted', 'verdict_state': row['state'],
                  'message': 'User explicitly associated the existing ACMP submission. No upload performed.'}
        self.storage.finish(subject, key, result)
        return result
