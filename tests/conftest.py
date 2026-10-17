import pytest
from cryptography.fernet import Fernet
from acmp_connect.config import Settings

@pytest.fixture
def settings(tmp_path):
    return Settings('http://localhost:8000', 'https://id.example/', 'https://id.example/jwks',
                    Fernet.generate_key().decode(), database=str(tmp_path/'db.sqlite'), dev=True,
                    portal_client_id='portal', authorization_endpoint='https://id.example/authorize',
                    token_endpoint='https://id.example/token')


