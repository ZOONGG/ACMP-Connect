"""Real JWT cryptography with a local mock OIDC provider, never external secrets."""
import base64
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient
from acmp_connect.auth import JWTVerifier, subject_key, READ, WRITE, MANAGE
from acmp_connect.mcp_server import create_app
from dataclasses import replace
from test_server import FakeClient, rpc


@contextmanager
def provider(settings):
    private_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update(kid='test-key',use='sig',alg='RS256')
    context = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            body = json.dumps({'keys':[jwk]}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        def do_POST(self):
            form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            context['form'] = form
            now = int(time.time())
            claims = {'iss':context['issuer'],'sub':'identity-1','aud':'portal','iat':now,'exp':now+300,'nonce':context['nonce']}
            token = jwt.encode(claims,private_key,algorithm='RS256',headers={'kid':'test-key'})
            body = json.dumps({'id_token':token,'access_token':'unused'}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    issuer = f'http://127.0.0.1:{server.server_port}/'
    context['issuer'] = issuer
    s = replace(settings,issuer=issuer,jwks_url=issuer+'jwks',authorization_endpoint=issuer+'authorize',token_endpoint=issuer+'token')
    try:
        yield s,private_key,context
    finally:
        server.shutdown();server.server_close();thread.join()


@pytest.mark.asyncio
async def test_real_jwt_signature_issuer_audience_expiry(settings):
    with provider(settings) as (s,key,context):
        verifier = JWTVerifier(s)
        now = int(time.time())
        claims = {'iss':s.issuer,'sub':'alice','aud':s.resource,'iat':now,'exp':now+300,'scope':READ+' '+WRITE}
        def encode(values,signing_key=key):
            return jwt.encode(values,signing_key,algorithm='RS256',headers={'kid':'test-key'})
        token = await verifier.verify_token(encode(claims))
        assert token.subject == subject_key(s.issuer,'alice')
        for changes in [{'aud':'another-resource'}, {'iss':'https://evil.example/'}, {'exp':now-100},
                        {'sub':''}, {'scope':WRITE}, {'scope':['unexpected']}]:
            assert await verifier.verify_token(encode({**claims,**changes})) is None
        wrong_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        assert await verifier.verify_token(encode(claims,wrong_key)) is None
        assert await verifier.verify_token('malformed') is None


@pytest.mark.asyncio
async def test_auth0_audience_array_and_authorized_party(settings):
    with provider(settings) as (s, key, _):
        verifier = JWTVerifier(s)
        now = int(time.time())
        claims = {'iss': s.issuer, 'sub': 'auth0|private-user',
                  'aud': [s.resource, s.issuer + 'userinfo'],
                  'azp': 'chatgpt-client', 'iat': now, 'exp': now + 300,
                  'scope': 'openid profile email ' + READ}
        def encode(values):
            return jwt.encode(values, key, algorithm='RS256', headers={'kid': 'test-key'})
        token = await verifier.verify_token(encode(claims))
        assert token is not None and token.client_id == 'chatgpt-client'
        assert token.resource == s.resource and READ in token.scopes
        assert token.subject == subject_key(s.issuer, 'auth0|private-user')
        # Neither the origin nor userinfo is the MCP API audience.
        for audience in [s.public_url, s.issuer + 'userinfo', s.resource + '/']:
            assert await verifier.verify_token(encode({**claims, 'aud': audience})) is None


def test_production_https_discovery_challenge_and_read_without_acmp(settings):
    from mcp.server.auth.provider import AccessToken
    s = replace(settings, public_url='https://private-acmp.up.railway.app', dev=False)
    class ReadVerifier:
        async def verify_token(self, token):
            if token == 'private-read':
                return AccessToken(token=token, client_id='chatgpt-client', scopes=[READ],
                                   subject='private-user', expires_at=int(time.time()) + 300,
                                   resource=s.resource)
    app = create_app(s, verifier=ReadVerifier(), client_factory=FakeClient)
    with TestClient(app, base_url=s.public_url) as client:
        response = client.post('/mcp', json={})
        assert response.status_code == 401
        challenge = response.headers['www-authenticate']
        import re
        metadata_url = re.search(r'resource_metadata="([^"]+)"', challenge).group(1)
        assert metadata_url == s.public_url + '/.well-known/oauth-protected-resource/mcp'
        expected = {'resource': s.resource, 'authorization_servers': [s.issuer],
                    'scopes_supported': [READ, WRITE, MANAGE]}
        assert client.get(metadata_url).json() == expected
        assert client.get('/.well-known/oauth-protected-resource').json() == expected
        assert client.get('/healthz', headers={'Host': 'healthcheck.railway.app'}).status_code == 200
        result = rpc(client, 'tools/call', {'name': 'get_problem', 'arguments': {'problem_id': 1}},
                     token='private-read').json()['result']
        assert not result.get('isError') and result['structuredContent']['title'] == 'A+B'
        with app.state.storage.db() as db:
            assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 0


def test_oidc_portal_end_to_end_with_mock_provider(settings):
    with provider(settings) as (s,key,context):
        app = create_app(s,client_factory=FakeClient)
        with TestClient(app,base_url=s.public_url) as client:
            response = client.get('/connect/login',follow_redirects=False)
            query = parse_qs(urlsplit(response.headers['location']).query)
            context['nonce'] = query['nonce'][0]
            response = client.get('/connect/callback',params={'state':query['state'][0],'code':'mock-code','iss':s.issuer},follow_redirects=False)
            assert response.status_code == 303
            assert 'HttpOnly' in response.headers['set-cookie']
            verifier = context['form']['code_verifier'][0]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            assert challenge == query['code_challenge'][0]
            session = app.state.storage.read_ticket(client.cookies['acmp_portal'],'portal')
            assert session['subject'] == subject_key(s.issuer,'identity-1')
            response = client.post('/connect/account',data={'csrf':session['csrf'],'login':'mock-login','password':'mock-password'},
                                   headers={'Origin':s.public_url},follow_redirects=False)
            assert response.status_code == 303
            now=int(time.time())
            access=jwt.encode({'iss':s.issuer,'sub':'identity-1','aud':s.resource,'iat':now,'exp':now+300,
                               'scope':' '.join([READ,WRITE,MANAGE])},key,algorithm='RS256',headers={'kid':'test-key'})
            result=rpc(client,'tools/call',{'name':'get_account_status','arguments':{}},token=access).json()['result']
            assert result['structuredContent']['connected'] is True
            assert result['structuredContent']['acmp_user_id'] == 42
            # State is single-use, and callback cannot be replayed.
            assert client.get('/connect/callback',params={'state':query['state'][0],'code':'mock-code'}).status_code == 400
            response=client.post('/connect/delete',data={'csrf':session['csrf']},headers={'Origin':s.public_url})
            assert response.status_code == 200
            assert app.state.storage.read_ticket(session.get('token',''),'portal') is None
            assert client.get('/connect').status_code == 200

@pytest.mark.asyncio
async def test_official_mcp_client_over_real_http(settings):
    import asyncio
    import socket
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    port=sock.getsockname()[1]
    with provider(replace(settings,public_url=f'http://127.0.0.1:{port}')) as (s,key,context):
        app=create_app(s,client_factory=FakeClient)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                await asyncio.sleep(.05)
            assert server.started
            now=int(time.time())
            token=jwt.encode({'iss':s.issuer,'sub':'sdk-user','aud':s.resource,'iat':now,'exp':now+300,'scope':READ},key,
                             algorithm='RS256',headers={'kid':'test-key'})
            async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token}) as client:
                async with streamable_http_client(s.resource,http_client=client) as (read,write,_):
                    async with ClientSession(read,write) as session:
                        await session.initialize()
                        tools=await session.list_tools()
                        assert len(tools.tools)==8
                        result=await session.call_tool('get_problem',{'problem_id':1})
                        assert not result.isError and result.structuredContent['title']=='A+B'
        finally:
            server.should_exit=True
            await asyncio.to_thread(thread.join,5)
            sock.close()
