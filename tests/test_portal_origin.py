"""Portal form policy and mutation boundaries, with no external ACMP calls."""
from dataclasses import replace
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient
from starlette.responses import Response

from acmp_connect.mcp_server import create_app
from acmp_connect.portal import COOKIE, Portal
from test_server import FakeClient


@pytest.fixture
def portal(settings):
    settings = replace(settings, public_url='https://portal.example', dev=False)
    app = create_app(settings, client_factory=FakeClient)
    app.state.service.connect = Mock()
    with TestClient(app, base_url=settings.public_url) as client:
        ticket = app.state.storage.ticket('portal', {'subject': 'test-user', 'csrf': 'private-csrf'})
        response = Response()
        Portal(app.state.storage, settings, app.state.service, None).cookie(response, COOKIE, ticket, 1800)
        cookie = response.headers['set-cookie']
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
        client.cookies.set(COOKIE, ticket, domain='portal.example', path='/connect')
        yield client, app


def test_form_policy_preserves_origin_and_callback_privacy(portal):
    client, _ = portal
    response = client.get('/connect')
    assert response.headers['referrer-policy'] == 'same-origin'
    assert 'method="post" action="/connect/account"' in response.text
    assert "form-action 'self'" in response.headers['content-security-policy']
    assert client.get('/connect/callback').headers['referrer-policy'] == 'no-referrer'


@pytest.mark.parametrize('path', ['account', 'disconnect', 'delete'])
@pytest.mark.parametrize('origin', [None, 'null', 'https://evil.example',
                                  'https://portal.example.evil.example', 'http://portal.example'])
def test_reject_untrusted_origin_even_with_valid_csrf(portal, caplog, path, origin):
    client, app = portal
    headers = {'Referer': 'https://portal.example/connect', 'Sec-Fetch-Site': 'same-origin'}
    if origin is not None:
        headers['Origin'] = origin
    response = client.post('/connect/' + path, headers=headers, data={
        'csrf': 'private-csrf', 'login': 'private-login', 'password': 'private-password'})
    assert response.status_code == 403 and 'Origin check failed' in response.text
    app.state.service.connect.assert_not_called()
    assert app.state.storage.read_ticket(client.cookies[COOKIE], 'portal') is not None
    message = next(r.getMessage() for r in caplog.records if 'portal_origin_rejected' in r.getMessage())
    assert 'referer_matches=True' in message
    for secret in ['private-csrf', 'private-login', 'private-password', 'portal.example', 'evil.example', client.cookies[COOKIE]]:
        assert secret not in message


@pytest.mark.parametrize('csrf', [None, '', 'wrong'])
@pytest.mark.parametrize('path', ['account', 'disconnect', 'delete'])
def test_reject_invalid_csrf_with_correct_origin(portal, csrf, path):
    client, app = portal
    response = client.post('/connect/' + path, headers={'Origin': 'https://portal.example'},
                           data={} if csrf is None else {'csrf': csrf})
    assert response.status_code == 403 and 'CSRF check failed' in response.text
    app.state.service.connect.assert_not_called()


def test_same_origin_post_reaches_service(portal):
    client, app = portal
    response = client.post('/connect/account', headers={
        'Origin': 'https://portal.example', 'Referer': 'https://portal.example/connect',
        'Sec-Fetch-Site': 'same-origin'}, data={
            'csrf': 'private-csrf', 'login': 'test-login', 'password': 'test-password'}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/connect'
    app.state.service.connect.assert_called_once_with('test-user', 'test-login', 'test-password')


def test_post_requires_portal_session(portal):
    client, app = portal
    client.cookies.clear()
    response = client.post('/connect/account', headers={'Origin': 'https://portal.example'}, data={'csrf': 'private-csrf'})
    assert response.status_code == 401
    app.state.service.connect.assert_not_called()
