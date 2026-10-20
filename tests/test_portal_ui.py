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
    assert account.select_one('[name="csrf"]')['value'] == 'private-csrf'
    assert account.select_one('[name="password"]')['type'] == 'password'
    assert account.select_one('[name="password"]').get('value') is None
    for name in ('login', 'password'):
        assert soup.select_one(f'label[for="{name}"]')
    for path in ('disconnect', 'delete'):
        form = soup.select_one(f'form[action="/connect/{path}"]')
        assert form.select_one('details.confirm button[type="submit"]')
    assert soup.select_one('[name="confirm_delete"][required]')
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
