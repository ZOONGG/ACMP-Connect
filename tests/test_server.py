import json
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient
from mcp.server.auth.provider import AccessToken
from acmp_connect.acmp_client import ACMPClient, structured_problem, safe_course_url
from acmp_connect.client import ACMPError, authenticated_user, SafeRedirect
from acmp_connect.config import Settings
from acmp_connect.storage import Storage
from acmp_connect.service import Service
from acmp_connect.mcp_server import create_app
from acmp_connect.auth import subject_key, READ, WRITE, MANAGE

PAGE = '<a href="/?main=user&id=42">me</a><a href="/?main=exit">logout</a><h1>Task</h1><form action="/index.asp?main=update&mode=upload&id_task=1"></form><select name=lang><option value=c>GNU C 14</option><option value=cpp>GNU C++ 15</option></select>'
KEY = 'explicit-action-0001'


class FakeClient(ACMPClient):
    uploads = 0
    uncertain = False
    rows = []
    owner = 42
    def identity(self):
        return self.owner
    def request(self, path, *args):
        return PAGE
    def login(self, *args):
        return self.owner, PAGE
    def submissions(self, user, task=None, submission_id=None, page_index=0):
        if page_index:
            return []
        return [r for r in self.rows if r['user'] == user and (not task or r['task'] == task)]
    def upload(self, number, compiler, source):
        type(self).uploads += 1
        if self.uncertain:
            raise ACMPError('network')
        type(self).rows = [submission()]
        return 'ok'
    def matches_source(self, identifier, source):
        return True
    def problem(self, number):
        return {'id': number, 'title': 'A+B'}
    def topic(self, query):
        return {'tasks': [{'letter': 'A', 'id': 106}]}


def submission(identifier=101, task=1, user=42, verdict='Accepted', state='final'):
    return {'id': identifier, 'task': task, 'user': user, 'verdict': verdict, 'state': state,
            'test': None, 'time': '0.01', 'memory': '100 KB', 'url': 'https://acmp.ru/'}


@pytest.fixture
def service(settings):
    FakeClient.rows, FakeClient.uploads, FakeClient.uncertain, FakeClient.owner = [], 0, False, 42
    storage = Storage(settings.database, settings.encryption_key)
    storage.save_account('alice', 42, '[]', 3600)
    return Service(storage, settings, FakeClient)


def test_current_sidebar_identity_and_rejection():
    page = '<a href="/?main=exit">Exit</a><td class=menu_title>Info</td><a href="/index.asp?main=user&id=42">Мои задачи</a><h1>A+B</h1>'
    assert authenticated_user(page) == 42
    for p, match in [('<input type=password>', 'rejected'), ('<input name=captcha><input type=password>', 'CAPTCHA'),
                     ('<a href="/?main=user&id=42">public</a>', 'format changed')]:
        with pytest.raises(ACMPError, match=match):
            authenticated_user(p)


def test_cookie_roundtrip():
    import http.cookiejar
    c = ACMPClient()
    c.jar.set_cookie(http.cookiejar.Cookie(0,'secret','cookie',None,False,'acmp.ru',False,False,'/',True,True,None,True,None,None,{}))
    d = ACMPClient();d.load_cookies(c.dump_cookies())
    assert next(iter(d.jar)).value == 'cookie'


def test_storage_encryption_and_isolation(service):
    service.storage.save_account('alice',42,'sensitive-cookie',3600)
    assert b'sensitive-cookie' not in open(service.storage.path,'rb').read()
    assert service.storage.account('alice')[1] == 'sensitive-cookie'
    with pytest.raises(ACMPError):
        service.storage.account('bob')
    with pytest.raises(ACMPError):
        service.storage.save_account('bob',42,'[]',3600)
    token = service.storage.ticket('portal',{'subject':'alice'})
    assert service.storage.read_ticket(token,'portal',True) == {'subject':'alice'}
    assert service.storage.read_ticket(token,'portal') is None


@pytest.mark.parametrize('lang,compiler',[('C','c'),('C++','cpp')])
def test_submission_and_idempotency(service,lang,compiler):
    result = service.submit('alice',1,lang,'int main(){}',KEY)
    assert result['id'] == 101 and result['compiler'] == compiler
    assert service.submit('alice',1,lang,'int main(){}',KEY) == result
    assert FakeClient.uploads == 1
    with pytest.raises(ACMPError,match='different input'):
        service.submit('alice',1,lang,'different',KEY)
    with pytest.raises(ACMPError,match='cooldown'):
        service.submit('alice',1,lang,'int main(){}',KEY+'2')


def test_uncertain_is_durable_and_never_retried(service):
    FakeClient.uncertain = True
    result = service.submit('alice',1,'C++','int main(){}',KEY)
    assert result['state'] == 'uncertain'
    restarted = Service(Storage(service.storage.path,service.settings.encryption_key), service.settings, FakeClient)
    assert restarted.submit('alice',1,'C++','int main(){}',KEY) == result
    with pytest.raises(ACMPError,match='uncertain'):
        restarted.submit('alice',1,'C++','int main(){}',KEY+'2')
    assert FakeClient.uploads == 1
    FakeClient.rows = [submission()]
    assert restarted.reconcile('alice',KEY,101)['state'] == 'submitted'
    with pytest.raises(ACMPError):
        restarted.reconcile('bob',KEY,101)


def test_atomic_reservation(service):
    def reserve(_):
        return service.storage.reserve('alice',KEY,42,'hash',1,30)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve,range(4)))
    assert sum(r is None for r in results) == 1
    service.storage.recover_after_restart()
    assert service.storage.operation('alice',KEY)['state'] == 'uncertain'


def test_disconnect_and_delete(service):
    service.submit('alice',1,'C++','int main(){}',KEY)
    service.storage.disconnect('alice',True)
    with pytest.raises(ACMPError):
        service.storage.account('alice')
    assert service.storage.operation('alice',KEY) is None


@pytest.mark.parametrize('verdict,state',[('Accepted','final'),('Wrong answer','final'),('Compilation error','final'),('Testing','pending'),('unexpected','unknown')])
def test_verdict_isolation(service,verdict,state):
    FakeClient.rows = [submission(verdict=verdict,state=state),submission(102,user=99)]
    assert service.verdict('alice',101)['verdict'] == verdict
    with pytest.raises(ACMPError):
        service.verdict('alice',102)


def test_session_mismatch(service):
    FakeClient.owner = 99
    with pytest.raises(ACMPError,match='identity changed'):
        service.submit('alice',1,'C++','int main(){}',KEY)
    assert FakeClient.uploads == 0


@pytest.mark.parametrize('url',['https://evil.example/a','http://acmp.ru/asp/do/index.asp?main=topic','//evil.example/a','https://acmp.ru/asp/do/index.asp?main=exit','https://acmp.ru/asp/do/index.asp?main=topic&id_topic=1&id_topic=2'])
def test_topic_ssrf_rejected(url):
    with pytest.raises(ACMPError):
        safe_course_url(url)


class TestVerifier:
    async def verify_token(self, token):
        if token == 'read':
            scopes = [READ]
        elif token == 'alice':
            scopes = [READ, WRITE, MANAGE]
        else:
            return None
        return AccessToken(token=token,client_id='test',scopes=scopes,subject='alice',
                           expires_at=int(time.time()+300),resource='http://localhost:8000/mcp')


def rpc(client, method, params=None, token='alice', identifier=1):
    headers = {'Accept':'application/json, text/event-stream','Authorization':'Bearer '+token}
    return client.post('/mcp',json={'jsonrpc':'2.0','id':identifier,'method':method,'params':params or {}},headers=headers)


def test_mcp_http_tools_auth_scopes_and_schemas(settings):
    app = create_app(settings,TestVerifier(),FakeClient)
    app.state.storage.save_account('alice',42,'[]',3600)
    with TestClient(app,base_url=settings.public_url) as client:
        assert client.get('/healthz').json() == {'status':'ok'}
        response = client.post('/mcp',json={})
        assert response.status_code == 401
        assert 'resource_metadata=' in response.headers['www-authenticate']
        metadata = client.get('/.well-known/oauth-protected-resource/mcp').json()
        assert metadata['resource'] == settings.resource
        init = rpc(client,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
        assert init.status_code == 200 and 'result' in init.json()
        tools = rpc(client,'tools/list').json()['result']['tools']
        assert len(tools) == 8
        for tool in tools:
            assert tool.get('outputSchema')
            assert tool['_meta']['securitySchemes']
        result = rpc(client,'tools/call',{'name':'get_problem','arguments':{'problem_id':1}}).json()['result']
        assert result['structuredContent']['title'] == 'A+B'
        invalid = rpc(client,'tools/call',{'name':'get_problem','arguments':{'problem_id':0}}).json()['result']
        assert invalid['isError']
        denied = rpc(client,'tools/call',{'name':'submit_solution','arguments':{'problem_id':1,'language':'C++','source':'int main(){}','idempotency_key':KEY}},token='read').json()['result']
        assert denied['isError']


def test_portal_csrf_and_no_anonymous_link(settings):
    app = create_app(settings,TestVerifier(),FakeClient)
    with TestClient(app,base_url=settings.public_url) as client:
        assert client.post('/connect/account',data={'login':'x','password':'y'}).status_code == 401
        token = app.state.storage.ticket('portal',{'subject':'alice','csrf':'csrf'})
        client.cookies.set('acmp_portal',token,path='/connect')
        assert client.post('/connect/account',data={'csrf':'csrf'},headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post('/connect/account',data={'csrf':'wrong'},headers={'Origin':settings.public_url}).status_code == 403
        response = client.get('/connect')
        assert response.headers['cache-control'] == 'no-store'
        assert 'frame-ancestors' in response.headers['content-security-policy']
        response = client.get('/connect/login',follow_redirects=False)
        assert response.status_code == 303 and 'code_challenge_method=S256' in response.headers['location']
        assert client.get('/connect/callback?state=bad&code=bad').status_code == 400


def test_production_config_fails_closed(settings):
    with pytest.raises(ValueError):
        replace(settings,dev=False).validate()
    with pytest.raises(ValueError):
        replace(settings,issuer='').validate()

@pytest.mark.parametrize('code',[307,308])
def test_upload_redirect_is_not_replayed(code):
    import urllib.request
    req=urllib.request.Request('https://acmp.ru/upload',data=b'code')
    with pytest.raises(ACMPError,match='POST'):
        SafeRedirect().redirect_request(req,None,code,'redirect',{},'https://acmp.ru/next')


def test_redirect_origin_and_scheme():
    import urllib.request
    req=urllib.request.Request('https://acmp.ru/',data=b'credentials')
    for target in ['http://acmp.ru/','https://evil.example/','https://acmp.ru.evil.example/']:
        with pytest.raises(ACMPError):
            SafeRedirect().redirect_request(req,None,302,'redirect',{},target)
    redirected=SafeRedirect().redirect_request(req,None,302,'redirect',{},'https://acmp.ru/index.asp')
    assert redirected.data is None


def test_native_c_unavailable_never_uploads(service):
    with patch.object(FakeClient,'request',return_value=PAGE.replace('<option value=c>GNU C 14</option>','')):
        with pytest.raises(ACMPError,match='компилятора'):
            service.submit('alice',1,'C','int main(){}',KEY)
    assert FakeClient.uploads==0


@pytest.mark.parametrize('task,lang,source,key',[(0,'C++','code',KEY),(True,'C++','code',KEY),
    (1,'Python','code',KEY),(1,'C++','',KEY),(1,'C++','x'*131073,KEY),(1,'C++','\0',KEY),
    (1,'C++','😀',KEY),(1,'C++','code','short')],ids=['bad-id','bool-id','bad-language','empty','oversized','nul','unicode','bad-key'])
def test_invalid_submission_never_uploads(service,task,lang,source,key):
    with pytest.raises(ACMPError):
        service.submit('alice',task,lang,source,key)
    assert FakeClient.uploads==0


def test_pending_timeout_does_not_resubmit(service):
    FakeClient.rows=[submission(verdict='Testing',state='pending')]
    with patch('acmp_connect.service.time.monotonic',side_effect=[100,103]):
        result=service.verdict('alice',101,2)
    assert result['wait_timed_out'] and result['state']=='pending'
    assert FakeClient.uploads==0


def test_crash_reservation_blocks_disconnect_and_relink(service):
    service.storage.reserve('alice',KEY,42,'hash',1,30)
    with pytest.raises(ACMPError):service.storage.disconnect('alice',True)
    with pytest.raises(ACMPError):service.storage.save_account('alice',43,'[]',3600)


def test_structured_problem_samples_and_images():
    page='''ЗАДАЧА №564<h1>Fence</h1><i>Time: 1 sec; Memory: 16 MB</i>
    <p>10<sup>9</sup><img src=/images/task.png></p><h2>Входные данные</h2><p>Numbers</p>
    <h2>Выходные данные</h2><p>Area</p><table><tr><th>№</th><th>INPUT.TXT</th><th>OUTPUT.TXT</th></tr>
    <tr><td>1</td><td><pre>3\n1 1 1</pre></td><td>0.433<br>1 2 3</td></tr></table><h4>End</h4>'''
    result=structured_problem(page,564)
    assert result['examples']==[{'input':'3\n1 1 1','output':'0.433\n1 2 3'}]
    assert result['images']==['https://acmp.ru/images/task.png']
    assert result['limits']=='Time: 1 sec; Memory: 16 MB'
    assert '10^9' in result['statement']


def test_diagnostics_only_after_ownership_check(service):
    FakeClient.rows=[submission(verdict='Compilation error')]
    with patch.object(FakeClient,'diagnostics',return_value='error: missing semicolon') as diagnostics:
        assert service.verdict('alice',101)['compiler_log']=='error: missing semicolon'
        with pytest.raises(ACMPError):service.verdict('alice',99)
        assert diagnostics.call_count==1


def test_body_limit_and_health_host(settings):
    app=create_app(settings,TestVerifier(),FakeClient)
    with TestClient(app,base_url=settings.public_url) as client:
        assert client.post('/mcp',content=b'x'*(1024*1024+1)).status_code==413
        assert client.get('/healthz',headers={'Host':'healthcheck.railway.app'}).status_code==200
        assert client.get('/healthz',headers={'Host':'evil.example'}).status_code==400

def test_captcha_on_login_response_stops_before_followup():
    client=ACMPClient()
    with patch.object(client,'request',return_value='<form><input name=captcha></form>') as request:
        with pytest.raises(ACMPError,match='CAPTCHA'):
            client.login('mock','mock',1)
        assert request.call_count==1


def test_session_encryption_key_mismatch_requires_reconnect(service):
    storage=Storage(service.storage.path,Fernet.generate_key())
    with pytest.raises(ACMPError,match='decrypt'):
        storage.account('alice')


def test_expired_account_is_not_used(service):
    service.storage.save_account('alice',42,'[]',-1)
    with pytest.raises(ACMPError,match='expired'):
        service.submit('alice',1,'C++','int main(){}',KEY)
    assert FakeClient.uploads==0


def test_unrelated_submission_is_not_attributed(service):
    with patch.object(FakeClient,'matches_source',return_value=False):
        result=service.submit('alice',1,'C++','int main(){}',KEY)
    assert result['state']=='uncertain' and result['id'] is None
    assert FakeClient.uploads==1


def test_stored_source_match_ignores_only_line_endings():
    client=ACMPClient()
    page='<script type="syntaxhighlighter"><![CDATA[int main(){}\r\n]]></script>'
    with patch.object(client,'request',return_value=page):
        assert client.matches_source(101,b'int main(){}\n')
        assert not client.matches_source(101,b'int main(){return 1;}')
