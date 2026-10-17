"""Private dotenv loading and deployment environment precedence."""
import os

import pytest
from cryptography.fernet import Fernet

from acmp_connect.config import Settings


@pytest.fixture
def dotenv_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Restore dotenv's environment changes as well as explicit test overrides.
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for name in ('PUBLIC_URL', 'OAUTH_ISSUER', 'OAUTH_JWKS_URL',
                 'SESSION_ENCRYPTION_KEY', 'DATABASE_PATH', 'PORTAL_CLIENT_SECRET',
                 'ACMP_DEV', 'SUBMISSION_INTERVAL', 'ACMP_SESSION_TTL'):
        monkeypatch.delenv(name, raising=False)
    content = ('PUBLIC_URL=https://server.example\n'
               'OAUTH_ISSUER=https://issuer.example/\n'
               'OAUTH_JWKS_URL=https://issuer.example/jwks\n'
               f'SESSION_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n'
               'DATABASE_PATH=data/test.sqlite3\n'
               "PORTAL_CLIENT_SECRET='literal-${UNSET_VALUE}'\n")
    (tmp_path / '.env').write_text(content, encoding='utf-8')
    return tmp_path


def test_dotenv_loads_and_preserves_hosting_environment(dotenv_directory, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL', 'https://hosting.example')
    settings = Settings.from_env()
    assert settings.public_url == 'https://hosting.example'
    assert settings.issuer == 'https://issuer.example/'
    assert settings.database == 'data/test.sqlite3'
    assert settings.portal_client_secret == 'literal-${UNSET_VALUE}'
    Fernet(settings.encryption_key)


def test_pending_origin_fails_closed(dotenv_directory):
    path = dotenv_directory / '.env'
    path.write_text(path.read_text().replace('PUBLIC_URL=https://server.example', 'PUBLIC_URL='))
    with pytest.raises(ValueError, match='required'):
        Settings.from_env()


def test_does_not_search_parent_directories(dotenv_directory, monkeypatch):
    child = dotenv_directory / 'child'
    child.mkdir()
    monkeypatch.chdir(child)
    with pytest.raises(ValueError, match='required'):
        Settings.from_env()
