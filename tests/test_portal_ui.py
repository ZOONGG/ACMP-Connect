"""Focused rendering and form regressions for the connection portal."""
from unittest.mock import Mock
from bs4 import BeautifulSoup
import pytest
from acmp_connect.client import ACMPError
from acmp_connect.portal import page
from test_portal_origin import portal


def test_welcome_and_local_assets(portal):
    client, _ = portal
    client.cookies.clear()
    response = client.get('/connect')
    soup = BeautifulSoup(response.text, 'html.parser')
    assert soup.html['lang'] == 'ru'
    assert soup.select_one('a[href="/connect/login"]')
    assert not soup.select('script:not([src]), [style]')
    csp = response.headers['content-security-policy']
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert 'unsafe-' not in csp
    for asset in ['/connect/assets/portal.css', '/connect/assets/portal.js', '/connect/assets/mark.svg']:
        response = client.get(asset)
        assert response.status_code == 200
        assert response.headers['x-content-type-options'] == 'nosniff'
    assert client.get('/connect/assets/missing.css').status_code == 404


@pytest.mark.parametrize('connected', [False, True])
def test_account_states_and_confirmations(portal, connected):
    client, app = portal
    app.state.service.account_status = Mock(return_value={'connected': connected, 'acmp_user_id': 42})
    response = client.get('/connect')
    soup = BeautifulSoup(response.text, 'html.parser')
    account = soup.select_one('form[action="/connect/account"]')
    assert not soup.select('details, .steps, .state-icon, .account-card')
    if connected:
        assert account is None
        disconnect = soup.select_one('form[action="/connect/disconnect"]')
        assert disconnect.select_one('[name="csrf"]')['value'] == 'private-csrf'
        assert disconnect.button.text == 'Выйти'
        assert 'Аккаунт подключён' in response.text
    else:
        assert account.select_one('[name="csrf"]')['value'] == 'private-csrf'
        assert account.select_one('[name="password"]')['type'] == 'password'
        assert account.select_one('[name="password"]').get('value') is None
        for name in ('login', 'password'):
            assert soup.select_one(f'label[for="{name}"]')
        assert not soup.select_one('form[action="/connect/disconnect"]')
    assert soup.select_one('dialog form[action="/connect/delete"] [name="confirm_delete"][required]')
    assert ('Пользователь #42' in response.text) == connected


def test_failure_never_reflects_credentials(portal):
    client, app = portal
    app.state.service.connect.side_effect = ACMPError('<script>private-password</script>')
    response = client.post('/connect/account', headers={'Origin': 'https://portal.example'},
                           data={'csrf': 'private-csrf', 'login': 'private-login', 'password': 'private-password'})
    assert response.status_code == 400
    assert 'private-password' not in response.text
    assert 'private-login' not in response.text
    assert 'href="/connect"' in response.text


@pytest.mark.parametrize('action', ['disconnect', 'delete'])
def test_destructive_form_routes(portal, action):
    client, app = portal
    app.state.storage.disconnect = Mock()
    response = client.post('/connect/' + action, headers={'Origin': 'https://portal.example'},
                           data={'csrf': 'private-csrf'}, follow_redirects=False)
    app.state.storage.disconnect.assert_called_once_with('test-user', action == 'delete')
    if action == 'delete':
        assert response.status_code == 200 and 'Данные удалены' in response.text
        assert 'Max-Age=0' in response.headers['set-cookie']
    else:
        assert response.status_code == 303


def test_template_autoescapes_messages():
    rendered = page('<script>alert(1)</script>', 400).body.decode()
    assert '<script>alert(1)</script>' not in rendered
    assert '&lt;script&gt;' in rendered


def test_expired_sign_in_has_readable_retry(portal):
    client, _ = portal
    response = client.get('/connect/callback')
    assert response.status_code == 400
    assert 'Ссылка входа истекла' in response.text
    assert 'href="/connect/login"' in response.text


def test_disconnect_keeps_portal_session_and_returns_connection_form(portal):
    client, app = portal
    from acmp_connect.portal import COOKIE
    ticket = client.cookies[COOKIE]
    app.state.service.account_status = Mock(return_value={'connected': False})
    response = client.post('/connect/disconnect', headers={'Origin': 'https://portal.example'},
                           data={'csrf': 'private-csrf'})
    assert response.status_code == 200
    assert 'Подключить acmp.ru' in response.text
    assert client.cookies[COOKIE] == ticket
    assert app.state.storage.read_ticket(ticket, 'portal') is not None
