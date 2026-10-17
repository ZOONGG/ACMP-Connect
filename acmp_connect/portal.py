"""OIDC-authenticated connection page. ACMP passwords only live in the POST handler."""
import asyncio
import base64
import hashlib
import hmac
import html
import secrets
import urllib.parse
import httpx
import jwt
from starlette.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from starlette.routing import Route
from .auth import subject_key
from .client import ACMPError

COOKIE = 'acmp_portal'
LOGIN_COOKIE = 'acmp_login'


def page(body, status=200):
    return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width"><title>ACMP Connect</title>'
                        '<body><main><h1>ACMP Connect</h1>' + body + '</main></body></html>', status_code=status)


class Portal:
    def __init__(self, storage, settings, service, verifier):
        self.storage, self.settings, self.service, self.verifier = storage, settings, service, verifier

    def session(self, request):
        return self.storage.read_ticket(request.cookies.get(COOKIE, ''), 'portal')

    def cookie(self, response, name, value, ttl):
        response.set_cookie(name, value, max_age=ttl, secure=not self.settings.dev,
                            httponly=True, samesite='lax', path='/connect')

    async def connect(self, request):
        session = self.session(request)
        if not session:
            return page('<p>Sign in with the same identity you use for this plugin in ChatGPT.</p>'
                        '<a href="/connect/login">Sign in securely</a>')
        status = await asyncio.to_thread(self.service.account_status, session['subject'])
        label = ('Connected to ACMP user ' + str(status['acmp_user_id'])) if status['connected'] else 'ACMP account not connected'
        csrf = html.escape(session['csrf'], quote=True)
        return page(f'<p>{label}</p><p>Enter your acmp.ru credentials here only. Your password is sent to acmp.ru over HTTPS and is never saved.</p>'
                    f'<form method="post" action="/connect/account"><input type="hidden" name="csrf" value="{csrf}">'
                    '<label>ACMP login <input name="login" maxlength="128" autocomplete="username" required></label><br>'
                    '<label>ACMP password <input type="password" name="password" maxlength="512" autocomplete="current-password" required></label><br>'
                    '<button>Connect ACMP account</button></form>'
                    f'<form method="post" action="/connect/disconnect"><input type="hidden" name="csrf" value="{csrf}"><button>Disconnect account</button></form>'
                    f'<form method="post" action="/connect/delete"><input type="hidden" name="csrf" value="{csrf}"><button>Delete all my stored data</button></form>'
                    '<p>Disconnection does not delete submissions from acmp.ru. CAPTCHA is never bypassed.</p>')

    async def login(self, request):
        s = self.settings
        if not all([s.portal_client_id, s.authorization_endpoint, s.token_endpoint]):
            return page('<p>Operator must configure the OIDC portal client before linking accounts.</p>', 503)
        ip = request.client.host if request.client else 'unknown'
        try:
            self.storage.rate('oidc:' + ip, maximum=20, window=300)
        except ACMPError:
            return page('<p>Too many attempts. Try later.</p>', 429)
        binding, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        state = self.storage.ticket('oidc', {'binding': hashlib.sha256(binding.encode()).hexdigest(),
                                           'verifier': verifier, 'nonce': nonce}, ttl=600)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        query = urllib.parse.urlencode({'response_type': 'code', 'client_id': s.portal_client_id,
                                        'redirect_uri': s.public_url + '/connect/callback', 'scope': 'openid',
                                        'state': state, 'nonce': nonce, 'code_challenge': challenge,
                                        'code_challenge_method': 'S256'})
        response = RedirectResponse(s.authorization_endpoint + '?' + query, status_code=303)
        self.cookie(response, LOGIN_COOKIE, binding, 600)
        return response

    async def callback(self, request):
        state = self.storage.read_ticket(request.query_params.get('state', ''), 'oidc', consume=True)
        binding = hashlib.sha256(request.cookies.get(LOGIN_COOKIE, '').encode()).hexdigest()
        if not state or not hmac.compare_digest(binding, state['binding']) or not request.query_params.get('code'):
            return page('<p>Invalid or expired sign-in. Start again.</p>', 400)
        s = self.settings
        if request.query_params.get('iss', s.issuer) != s.issuer:
            return page('<p>Unexpected identity issuer.</p>', 400)
        form = {'grant_type': 'authorization_code', 'code': request.query_params['code'],
                'redirect_uri': s.public_url + '/connect/callback', 'client_id': s.portal_client_id,
                'code_verifier': state['verifier']}
        if s.portal_client_secret:
            form['client_secret'] = s.portal_client_secret
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(s.token_endpoint, data=form)
                response.raise_for_status()
                claims = await asyncio.to_thread(self.verifier.decode, response.json()['id_token'], s.portal_client_id)
            if not hmac.compare_digest(claims.get('nonce', ''), state['nonce']):
                raise ValueError('nonce mismatch')
            if claims.get('azp', s.portal_client_id) != s.portal_client_id:
                raise ValueError('authorized party mismatch')
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError, TypeError, OSError):
            return page('<p>Identity verification failed. Start sign-in again.</p>', 400)
        subject = subject_key(s.issuer, claims['sub'])
        token = self.storage.ticket('portal', {'subject': subject, 'csrf': secrets.token_urlsafe(32)}, ttl=1800)
        response = RedirectResponse('/connect', status_code=303)
        self.cookie(response, COOKIE, token, 1800)
        response.delete_cookie(LOGIN_COOKIE, path='/connect')
        return response

    async def mutate(self, request):
        session = self.session(request)
        if not session:
            return page('<p>Sign in first.</p>', 401)
        if request.headers.get('origin') != self.settings.public_url:
            return page('<p>Origin check failed.</p>', 403)
        form = await request.form(max_fields=5, max_files=0, max_part_size=8192)
        if not hmac.compare_digest(str(form.get('csrf', '')), session['csrf']):
            return page('<p>CSRF check failed.</p>', 403)
        try:
            if request.url.path == '/connect/account':
                await asyncio.to_thread(self.service.connect, session['subject'], str(form.get('login', '')), str(form.get('password', '')))
            else:
                delete = request.url.path == '/connect/delete'
                await asyncio.to_thread(self.storage.disconnect, session['subject'], delete)
                if delete:
                    response = page('<p>Your ACMP session and local records have been deleted. You can revoke the plugin at your identity provider and in ChatGPT.</p>')
                    response.delete_cookie(COOKIE, path='/connect')
                    return response
        except ACMPError as exc:
            return page('<p>' + html.escape(str(exc)) + '</p><a href="/connect">Return</a>', 400)
        return RedirectResponse('/connect', status_code=303)

    def routes(self):
        return [Route('/connect', self.connect), Route('/connect/login', self.login),
                Route('/connect/callback', self.callback),
                *[Route('/connect/' + p, self.mutate, methods=['POST']) for p in ['account', 'disconnect', 'delete']]]
