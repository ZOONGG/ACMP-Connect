"""OIDC-authenticated connection page. ACMP passwords only live in the POST handler."""
import asyncio
import base64
import hashlib
import hmac
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
import logging
import secrets
import urllib.parse
import httpx
import jwt
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from .auth import subject_key
from .client import ACMPError

COOKIE = 'acmp_portal'
LOGIN_COOKIE = 'acmp_login'
logger = logging.getLogger(__name__)


def callback_error(stage, exc):
    # Use only fixed categories: exception messages can contain tokens or claims.
    categories = (
        (jwt.InvalidSignatureError, 'invalid_signature'),
        (jwt.InvalidAudienceError, 'invalid_audience'),
        (jwt.InvalidIssuerError, 'invalid_issuer'),
        (jwt.ExpiredSignatureError, 'expired_token'),
        (jwt.ImmatureSignatureError, 'immature_token'),
        (jwt.InvalidIssuedAtError, 'invalid_issued_at'),
        (jwt.MissingRequiredClaimError, 'missing_claim'),
        (jwt.InvalidAlgorithmError, 'invalid_algorithm'),
        (jwt.PyJWKClientConnectionError, 'jwks_connection'),
        (jwt.PyJWKClientError, 'jwks_key'),
        (jwt.PyJWTError, 'invalid_jwt'),
        (httpx.HTTPStatusError, 'http_status'),
        (httpx.HTTPError, 'http_transport'),
        (KeyError, 'missing_field'),
        (TypeError, 'invalid_type'),
        (ValueError, 'invalid_value'),
        (OSError, 'io_error'),
    )
    category = next((label for kind, label in categories if isinstance(exc, kind)), 'verification_failed')
    logger.warning('portal_callback stage=%s category=%s', stage, category)


ASSETS = Path(__file__).parent / 'portal_assets'
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent / 'templates'),
                        autoescape=select_autoescape(['html']))


def page(message='', status=200, **context):
    return HTMLResponse(TEMPLATES.get_template('portal.html').render(
        message=message, error=status >= 400, **context), status_code=status)


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
            return page(view='welcome')
        status = await asyncio.to_thread(self.service.account_status, session['subject'])
        return page(view='account', account=status, csrf=session['csrf'])

    async def login(self, request):
        s = self.settings
        if not all([s.portal_client_id, s.authorization_endpoint, s.token_endpoint]):
            return page('Вход временно недоступен. Попробуйте позже.', 503)
        ip = request.client.host if request.client else 'unknown'
        try:
            self.storage.rate('oidc:' + ip, maximum=20, window=300)
        except ACMPError:
            return page('Слишком много попыток входа. Подождите несколько минут.', 429)
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
            logger.warning('portal_callback stage=state category=invalid_sign_in')
            return page('Ссылка входа истекла или уже использована. Начните вход заново.', 400)
        s = self.settings
        if request.query_params.get('iss', s.issuer) != s.issuer:
            logger.warning('portal_callback stage=response_issuer category=invalid_issuer')
            return page('Не удалось подтвердить источник авторизации. Повторите безопасный вход.', 400)
        form = {'grant_type': 'authorization_code', 'code': request.query_params['code'],
                'redirect_uri': s.public_url + '/connect/callback', 'client_id': s.portal_client_id,
                'code_verifier': state['verifier']}
        if s.portal_client_secret:
            form['client_secret'] = s.portal_client_secret
        stage = 'token_exchange'
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(s.token_endpoint, data=form)
                response.raise_for_status()
                stage = 'token_response'
                id_token = response.json()['id_token']
                stage = 'id_token'
                claims = await asyncio.to_thread(self.verifier.decode, id_token, s.portal_client_id)
            stage = 'nonce'
            if not hmac.compare_digest(claims.get('nonce', ''), state['nonce']):
                raise ValueError('nonce mismatch')
            stage = 'authorized_party'
            if claims.get('azp', s.portal_client_id) != s.portal_client_id:
                raise ValueError('authorized party mismatch')
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError, TypeError, OSError) as exc:
            callback_error(stage, exc)
            return page('Не удалось подтвердить вашу личность. Повторите вход через Auth0.', 400)
        subject = subject_key(s.issuer, claims['sub'])
        token = self.storage.ticket('portal', {'subject': subject, 'csrf': secrets.token_urlsafe(32)}, ttl=1800)
        response = RedirectResponse('/connect', status_code=303)
        self.cookie(response, COOKIE, token, 1800)
        response.delete_cookie(LOGIN_COOKIE, path='/connect')
        logger.info('portal_callback stage=complete category=success')
        return response

    async def mutate(self, request):
        session = self.session(request)
        if not session:
            return page('Сессия истекла. Войдите снова, чтобы продолжить.', 401)
        if request.headers.get('origin') != self.settings.public_url:
            referer = request.headers.get('referer', '')
            try:
                parsed = urllib.parse.urlsplit(referer)
                referer_matches = parsed.scheme + '://' + parsed.netloc == self.settings.public_url
            except ValueError:
                referer_matches = False
            logger.warning(
                'portal_origin_rejected origin_present=%s origin_matches=%s '
                'referer_present=%s referer_matches=%s fetch_site_present=%s fetch_site_same_origin=%s',
                'origin' in request.headers, False, 'referer' in request.headers, referer_matches,
                'sec-fetch-site' in request.headers, request.headers.get('sec-fetch-site') == 'same-origin')
            return page('Origin check failed. Откройте портал заново и повторите действие.', 403, retry='/connect')
        form = await request.form(max_fields=5, max_files=0, max_part_size=8192)
        if not hmac.compare_digest(str(form.get('csrf', '')), session['csrf']):
            return page('CSRF check failed. Обновите страницу перед повторной попыткой.', 403, retry='/connect')
        try:
            if request.url.path == '/connect/account':
                await asyncio.to_thread(self.service.connect, session['subject'], str(form.get('login', '')), str(form.get('password', '')))
            else:
                delete = request.url.path == '/connect/delete'
                await asyncio.to_thread(self.storage.disconnect, session['subject'], delete)
                if delete:
                    response = page('Сессия ACMP и локальные записи удалены. Доступ плагина можно также отозвать в ChatGPT и у провайдера авторизации.', view='deleted')
                    response.delete_cookie(COOKIE, path='/connect')
                    return response
        except ACMPError as exc:
            message = 'Не удалось подключить аккаунт. Проверьте данные и повторите попытку.'
            if 'CAPTCHA' in str(exc):
                message = 'acmp.ru запросил CAPTCHA. Пройдите проверку на acmp.ru и повторите подключение.'
            elif 'сети' in str(exc) or 'HTTP' in str(exc):
                message = 'acmp.ru временно недоступен. Попробуйте подключиться позже.'
            return page(message, 400, retry='/connect')
        return RedirectResponse('/connect', status_code=303)

    def routes(self):
        return [Mount('/connect/assets', app=StaticFiles(directory=ASSETS)), Route('/connect', self.connect), Route('/connect/login', self.login),
                Route('/connect/callback', self.callback),
                *[Route('/connect/' + p, self.mutate, methods=['POST']) for p in ['account', 'disconnect', 'delete']]]
