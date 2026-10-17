"""Validated deployment configuration. Production never falls back to no auth."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    public_url: str
    issuer: str
    jwks_url: str
    encryption_key: str
    database: str = 'data/acmp.sqlite3'
    portal_client_id: str = ''
    portal_client_secret: str = ''
    authorization_endpoint: str = ''
    token_endpoint: str = ''
    dev: bool = False
    submission_interval: int = 30
    session_ttl: int = 604800

    @property
    def resource(self):
        return self.public_url + '/mcp'

    def validate(self):
        for value in [self.public_url, self.issuer, self.jwks_url,
                      self.authorization_endpoint, self.token_endpoint]:
            if not value:
                continue
            u = urlsplit(value)
            local = self.dev and u.hostname in {'localhost', '127.0.0.1'}
            if not u.netloc or (u.scheme != 'https' and not (local and u.scheme == 'http')) or u.username or u.password or u.fragment or u.query:
                raise ValueError('Configuration URLs must be absolute HTTPS URLs without credentials, query or fragment.')
        if not self.public_url or not self.issuer or not self.jwks_url or not self.encryption_key:
            raise ValueError('PUBLIC_URL, OAUTH_ISSUER, OAUTH_JWKS_URL and SESSION_ENCRYPTION_KEY are required.')
        if urlsplit(self.public_url).path not in {'', '/'} or self.public_url.endswith('/'):
            raise ValueError('PUBLIC_URL must be an origin without a trailing slash.')
        if self.submission_interval < 10 or not 60 <= self.session_ttl <= 2592000:
            raise ValueError('Submission interval must be >=10 seconds; session TTL 60..2592000.')
        return self

    @classmethod
    def from_env(cls):
        return cls(public_url=os.getenv('PUBLIC_URL', ''), issuer=os.getenv('OAUTH_ISSUER', ''),
                   jwks_url=os.getenv('OAUTH_JWKS_URL', ''), encryption_key=os.getenv('SESSION_ENCRYPTION_KEY', ''),
                   database=os.getenv('DATABASE_PATH', 'data/acmp.sqlite3'),
                   portal_client_id=os.getenv('PORTAL_CLIENT_ID', ''),
                   portal_client_secret=os.getenv('PORTAL_CLIENT_SECRET', ''),
                   authorization_endpoint=os.getenv('OIDC_AUTHORIZATION_ENDPOINT', ''),
                   token_endpoint=os.getenv('OIDC_TOKEN_ENDPOINT', ''), dev=os.getenv('ACMP_DEV') == '1',
                   submission_interval=int(os.getenv('SUBMISSION_INTERVAL', '30')),
                   session_ttl=int(os.getenv('ACMP_SESSION_TTL', '604800'))).validate()
