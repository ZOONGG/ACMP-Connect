"""Use an established OAuth/OIDC issuer; never treat ACMP credentials as MCP tokens."""
import asyncio
import hashlib
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.middleware.auth_context import get_access_token

READ = 'acmp:read'
WRITE = 'acmp:submit'
MANAGE = 'acmp:manage'
SCOPES = [READ, WRITE, MANAGE]


def subject_key(issuer, subject):
    return hashlib.sha256((issuer + '\0' + subject).encode()).hexdigest()


class JWTVerifier(TokenVerifier):
    def __init__(self, settings):
        self.settings = settings
        self.jwks = jwt.PyJWKClient(settings.jwks_url, cache_jwk_set=True, lifespan=300, timeout=10)

    def decode(self, token, audience):
        if len(token) > 16384:
            raise jwt.InvalidTokenError('Token too long')
        key = self.jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=audience,
                            issuer=self.settings.issuer, options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']})
        if not isinstance(claims['sub'], str) or not claims['sub'].strip():
            raise jwt.InvalidTokenError('Missing subject')
        return claims

    async def verify_token(self, token):
        try:
            claims = await asyncio.to_thread(self.decode, token, self.settings.resource)
            scope = claims.get('scope', '')
            if not isinstance(scope, str):
                return None
            scopes = scope.split()
            if READ not in scopes:
                return None
            return AccessToken(token=token, client_id=claims.get('azp', claims.get('client_id', 'oauth')),
                               scopes=scopes, expires_at=int(claims['exp']), resource=self.settings.resource,
                               subject=subject_key(self.settings.issuer, claims['sub']))
        except (jwt.PyJWTError, ValueError, TypeError, OSError):
            return None


def current_subject(scope=READ):
    token = get_access_token()
    if not token or not token.subject or scope not in token.scopes:
        raise PermissionError('OAuth authentication with the required scope is needed.')
    return token.subject
