"""SQLite transactions coordinate a single Railway instance and survive restarts."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .client import ACMPError


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Storage:
    def __init__(self, path, key):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS accounts (
                subject TEXT PRIMARY KEY, acmp_id INTEGER UNIQUE NOT NULL,
                cookies BLOB NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
                subject TEXT NOT NULL, key TEXT NOT NULL, acmp_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL, task INTEGER NOT NULL, created REAL NOT NULL,
                state TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(subject,key));
            CREATE INDEX IF NOT EXISTS operations_account ON operations(acmp_id,created);
            CREATE TABLE IF NOT EXISTS tickets (
                token TEXT PRIMARY KEY, kind TEXT NOT NULL, value BLOB NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
            ''')
        try:
            Path(path).chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_account(self, subject, acmp_id, cookies, ttl):
        payload = self.cipher.encrypt(cookies.encode())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT 1 FROM operations WHERE subject=? AND state='reserved'", (subject,)).fetchone()
            if active:
                raise ACMPError('An upload is in progress. Wait before changing the linked account.')
            existing = db.execute('SELECT subject FROM accounts WHERE acmp_id=?', (acmp_id,)).fetchone()
            if existing and existing['subject'] != subject:
                raise ACMPError('This ACMP account is linked to another identity. Disconnect that identity first.')
            db.execute('INSERT INTO accounts VALUES(?,?,?,?) ON CONFLICT(subject) DO UPDATE SET acmp_id=excluded.acmp_id,cookies=excluded.cookies,expires=excluded.expires',
                       (subject, acmp_id, payload, time.time() + ttl))

    def account(self, subject):
        with self.db() as db:
            row = db.execute('SELECT * FROM accounts WHERE subject=?', (subject,)).fetchone()
        if not row or row['expires'] <= time.time():
            raise ACMPError('ACMP account is not connected or session expired. Open the connection page.')
        try:
            return row['acmp_id'], self.cipher.decrypt(row['cookies']).decode()
        except InvalidToken:
            raise ACMPError('Stored session cannot be decrypted. Reconnect your ACMP account.') from None

    def disconnect(self, subject, delete=False):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Never delete a reservation while its worker may still POST.
            active = db.execute("SELECT 1 FROM operations WHERE subject=? AND state='reserved'", (subject,)).fetchone()
            if active:
                raise ACMPError('An upload may still be in progress. Wait for its result before disconnecting.')
            db.execute('DELETE FROM accounts WHERE subject=?', (subject,))
            if delete:
                db.execute('DELETE FROM operations WHERE subject=?', (subject,))
                # Tickets are encrypted; enumerate and remove only this identity.
                for row in db.execute('SELECT token,value FROM tickets').fetchall():
                    value = json.loads(self.cipher.decrypt(row['value']))
                    if value.get('subject') == subject:
                        db.execute('DELETE FROM tickets WHERE token=?', (row['token'],))

    def ticket(self, kind, value, ttl=600):
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM tickets WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO tickets VALUES(?,?,?,?)',
                       (digest(token), kind, self.cipher.encrypt(json.dumps(value).encode()), time.time() + ttl))
        return token

    def read_ticket(self, token, kind, consume=False):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tickets WHERE token=? AND kind=? AND expires>?',
                             (digest(token), kind, time.time())).fetchone()
            if not row:
                return None
            if consume:
                db.execute('DELETE FROM tickets WHERE token=?', (digest(token),))
            return json.loads(self.cipher.decrypt(row['value']))

    def rate(self, key, maximum=20, window=60):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            db.execute('DELETE FROM limits WHERE started<?', (now - max(window, 3600),))
            row = db.execute('SELECT * FROM limits WHERE key=?', (key,)).fetchone()
            if not row or row['started'] <= now - window:
                db.execute('INSERT OR REPLACE INTO limits VALUES(?,?,1)', (key, now))
            elif row['count'] >= maximum:
                raise ACMPError('Rate limit reached. Wait before trying again.')
            else:
                db.execute('UPDATE limits SET count=count+1 WHERE key=?', (key,))

    def reserve(self, subject, key, acmp_id, fingerprint, task, interval):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM operations WHERE subject=? AND key=?', (subject, key)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise ACMPError('Idempotency key was already used with different input.')
                return json.loads(row['result'])
            linked = db.execute('SELECT acmp_id,expires FROM accounts WHERE subject=?', (subject,)).fetchone()
            if not linked or linked['acmp_id'] != acmp_id or linked['expires'] <= time.time():
                raise ACMPError('Account link changed before submission. No upload performed.')
            # Uncertain operations deliberately block every further upload on this
            # account until explicitly reconciled, including after a process crash.
            busy = db.execute("SELECT 1 FROM operations WHERE acmp_id=? AND state IN ('reserved','uncertain')", (acmp_id,)).fetchone()
            if busy:
                raise ACMPError('An upload is in progress or uncertain. Reconcile it before another submission.')
            recent = db.execute('SELECT max(created) FROM operations WHERE acmp_id=?', (acmp_id,)).fetchone()[0]
            if recent and time.time() - recent < interval:
                raise ACMPError('Submission cooldown active. Wait before a new explicit submission.')
            initial = {'operation_key': key, 'state': 'uncertain', 'id': None,
                       'message': 'Upload reserved. Do not retry with a new key; check recent submissions.'}
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?)',
                       (subject, key, acmp_id, fingerprint, task, time.time(), 'reserved', json.dumps(initial)))
            return None

    def finish(self, subject, key, result):
        with self.db() as db:
            db.execute('UPDATE operations SET state=?,result=? WHERE subject=? AND key=?',
                       (result['state'], json.dumps(result), subject, key))

    def operation(self, subject, key):
        with self.db() as db:
            row = db.execute('SELECT * FROM operations WHERE subject=? AND key=?', (subject, key)).fetchone()
            return dict(row) if row else None

    def recover_after_restart(self):
        with self.db() as db:
            db.execute("UPDATE operations SET state='uncertain' WHERE state='reserved'")
