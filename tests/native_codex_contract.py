"""Run with PYTHONPATH pointing to the patched official OpenJarvis src tree."""
import json
import os
import tempfile

_RUNTIME = tempfile.TemporaryDirectory(prefix="jarvis-native-test-")
os.environ["OPENJARVIS_HOME"] = _RUNTIME.name
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from openjarvis.engine.cloud import CloudEngine
from openjarvis.engine.multi import MultiEngine
from openjarvis.core.types import Message, Role
from openjarvis.core.config import JarvisConfig
from openjarvis.server.app import create_app
from openjarvis.server.cloud_router import get_provider

class NativeCodexContract(unittest.TestCase):
    def engine(self):
        engine = CloudEngine.__new__(CloudEngine)
        engine._codex_client = {'token': 'synthetic', 'url': 'https://chatgpt.com/backend-api/codex/responses'}
        return engine

    def test_history_roles(self):
        _, messages = self.engine()._codex_build_input([
            Message(Role.USER, 'question'), Message(Role.ASSISTANT, 'answer')])
        self.assertEqual(messages[0]['content'][0]['type'], 'input_text')
        self.assertEqual(messages[1]['content'][0]['type'], 'output_text')

    def test_sync_chatgpt_aggregates_terminal_response(self):
        response = Mock()
        response.iter_lines.return_value = [
            'data: '+json.dumps({'type':'response.completed','response':{
                'output':[{'type':'message','content':[{'type':'output_text','text':'Four.'}]}],
                'usage':{'input_tokens':3,'output_tokens':2}}})]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('openjarvis.engine.cloud.httpx.stream',return_value=response) as stream:
            result=self.engine()._generate_codex([Message(Role.USER,'2+2?')],model='codex/test',temperature=0,max_tokens=32)
        self.assertEqual(result['content'],'Four.')
        self.assertEqual(result['usage']['total_tokens'],5)
        self.assertTrue(stream.call_args.kwargs['json']['stream'])

    def test_sync_rejects_truncated_and_failed_streams(self):
        for records in ([],[{'type':'response.failed','error':{'message':'private'}}]):
            response=Mock()
            response.iter_lines.return_value=['data: '+json.dumps(x) for x in records]
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with patch('openjarvis.engine.cloud.httpx.stream',return_value=response):
                with self.assertRaises(Exception) as caught:
                    self.engine()._generate_codex([],model='codex/test',temperature=0,max_tokens=32)
                self.assertNotIn('private',str(caught.exception))

    def test_standard_api_retains_json_transport(self):
        engine=self.engine();engine._codex_client['url']='https://api.openai.com/v1/responses'
        response=Mock();response.json.return_value={'output_text':'Four.'}
        with patch('openjarvis.engine.cloud.httpx.post',return_value=response) as post:
            self.assertEqual(engine._generate_codex([],model='codex/test',temperature=0,max_tokens=32)['content'],'Four.')
        self.assertFalse(post.call_args.kwargs['json']['stream'])

    def test_codex_is_not_openrouter(self):
        self.assertEqual(get_provider('codex/gpt-6.1-sol'),'codex')
        self.assertEqual(get_provider('openrouter/openai/gpt-4o'),'openrouter')

    def test_ui_lists_configured_model_and_streams_via_native_engine(self):
        cloud=Mock();cloud.engine_id='cloud';cloud.is_cloud=True
        cloud.list_models.return_value=['codex/older-model']
        async def stream(*args,**kwargs):yield 'Native Codex answer'
        cloud.stream=stream
        engine=MultiEngine([('cloud',cloud)])
        cfg=JarvisConfig();cfg.analytics.enabled=False;cfg.traces.enabled=False
        cfg.agent.context_from_memory=False
        app=create_app(engine,'codex/gpt-6.1-sol',engine_name='multi',config=cfg)
        with TestClient(app) as client, patch('openjarvis.server.cloud_router.stream_cloud') as wrong_cloud, patch('openjarvis.server.cloud_router.stream_local') as wrong_local:
            ids=[x['id'] for x in client.get('/v1/models').json()['data']]
            self.assertEqual(ids[0], 'codex/gpt-6.1-sol')
            r=client.post('/v1/chat/completions',json={'model':'codex/gpt-6.1-sol','messages':[{'role':'user','content':'Hello'}],'stream':True})
            self.assertEqual(r.status_code,200)
            self.assertIn('Native Codex answer',r.text)
            wrong_cloud.assert_not_called();wrong_local.assert_not_called()

class AsyncCodexContract(unittest.IsolatedAsyncioTestCase):
    async def test_failed_or_truncated_stream_is_not_success(self):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        for records in ([], [{'type':'response.failed'}], [{'type':'response.incomplete'}]):
            async def lines():
                for record in records: yield 'data: '+json.dumps(record)
            @asynccontextmanager
            async def response(*args,**kwargs):
                yield SimpleNamespace(raise_for_status=lambda:None, aiter_lines=lines)
            @asynccontextmanager
            async def client(): yield SimpleNamespace(stream=response)
            engine=NativeCodexContract().engine()
            with patch('openjarvis.engine.cloud.httpx.AsyncClient',client):
                with self.assertRaises(Exception):
                    async for _ in engine._stream_codex([],model='codex/test',temperature=0,max_tokens=32): pass

    async def test_completed_stream_delivers_text(self):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        async def lines():
            yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'Four.'})
            yield 'data: '+json.dumps({'type':'response.completed'})
        @asynccontextmanager
        async def response(*args,**kwargs):
            yield SimpleNamespace(raise_for_status=lambda:None, aiter_lines=lines)
        @asynccontextmanager
        async def client(): yield SimpleNamespace(stream=response)
        engine=NativeCodexContract().engine()
        with patch('openjarvis.engine.cloud.httpx.AsyncClient',client):
            out=[x async for x in engine._stream_codex([],model='codex/test',temperature=0,max_tokens=32)]
        self.assertEqual(out,['Four.'])

class LocalCodexAuthContract(unittest.TestCase):
    def setUp(self):
        import pathlib
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / 'auth.json'
        from openjarvis.engine._codex_auth import LocalCodexAuth
        self.auth = LocalCodexAuth()
        self.auth.path = self.path

    def token(self, expires):
        import base64
        payload=base64.urlsafe_b64encode(json.dumps({'exp':expires}).encode()).decode().rstrip('=')
        return 'synthetic.'+payload+'.signature'

    def save(self, expires):
        value=self.token(expires)
        self.path.write_text(json.dumps({'tokens':{'access_token':value}}))
        self.path.chmod(0o600)
        return value

    def test_valid_cache_is_read_on_each_request_without_refresh(self):
        import time
        first=self.save(time.time()+1000)
        with patch.object(self.auth, '_refresh') as refresh:
            self.assertEqual(self.auth.access_token(),first)
            second=self.save(time.time()+2000)
            self.assertEqual(self.auth.access_token(),second)
            refresh.assert_not_called()

    def test_expiry_uses_codex_managed_refresh(self):
        import time
        self.save(0)
        async def refresh():self.save(time.time()+1000)
        with patch.object(self.auth,'_refresh',side_effect=refresh) as mocked:
            self.assertEqual(self.auth.access_token(),json.loads(self.path.read_text())['tokens']['access_token'])
            self.auth.access_token()
            self.assertEqual(mocked.call_count,1)

    def test_refresh_failure_is_sanitized_and_backed_off(self):
        self.save(0)
        with patch.object(self.auth,'_refresh',side_effect=ValueError('private sentinel')) as mocked:
            for _ in range(2):
                with self.assertRaises(Exception) as caught:self.auth.access_token()
                self.assertNotIn('private sentinel',str(caught.exception))
            self.assertEqual(mocked.call_count,1)

    def test_public_cache_is_rejected(self):
        self.save(9999999999);self.path.chmod(0o644)
        with self.assertRaises(Exception):self.auth.access_token()

    def test_missing_or_malformed_cache_is_sanitized(self):
        for contents in (None,'private sentinel'):
            if contents is not None:self.path.write_text(contents);self.path.chmod(0o600)
            with self.assertRaises(Exception) as caught:self.auth.access_token()
            self.assertNotIn('private sentinel',str(caught.exception))

    def test_opt_in_is_restricted_to_expected_https_endpoint(self):
        with patch.dict(os.environ,{'OPENAI_CODEX_USE_LOCAL_AUTH':'1','OPENAI_CODEX_API_KEY':'','OPENAI_CODEX_BASE_URL':'http://chatgpt.com/backend-api/codex'}):
            with self.assertRaises(Exception):CloudEngine()

    def test_external_token_takes_precedence(self):
        with patch.dict(os.environ,{'OPENAI_CODEX_USE_LOCAL_AUTH':'1','OPENAI_CODEX_API_KEY':'synthetic','OPENAI_CODEX_BASE_URL':'https://api.openai.com/v1'}):
            engine=CloudEngine()
            self.assertEqual(engine._codex_access_token(),'synthetic')
            self.assertNotIn('auth',engine._codex_client)
            engine.close()

    def test_default_model_not_limited_to_stale_catalog(self):
        from openjarvis.cli.serve import _resolve_server_model
        cfg=JarvisConfig();cfg.intelligence.default_model='codex/gpt-6.1-sol'
        cloud=Mock();cloud.list_models.return_value=['codex/older']
        engine=MultiEngine([('cloud',cloud)])
        self.assertEqual(_resolve_server_model(None,config=cfg,engine_name='multi',engine=engine,all_models={}), 'codex/gpt-6.1-sol')

class AuthProcessContract(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_only_uses_account_methods_and_reaps_process(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        from openjarvis.engine._codex_auth import LocalCodexAuth
        proc=SimpleNamespace(returncode=None,stdin=Mock(),stdout=Mock(),terminate=Mock(),kill=Mock(),wait=AsyncMock())
        proc.stdin.drain=AsyncMock()
        proc.stdout.readline=AsyncMock(side_effect=[b'{"id":1,"result":{}}\n',b'{"id":2,"result":{"account":{"type":"chatgpt"}}}\n'])
        with patch('openjarvis.engine._codex_auth.asyncio.create_subprocess_exec',AsyncMock(return_value=proc)) as spawn:
            await LocalCodexAuth()._refresh()
        methods=[json.loads(call.args[0])['method'] for call in proc.stdin.write.call_args_list]
        self.assertEqual(methods,['initialize','initialized','account/read'])
        self.assertEqual(spawn.call_args.args,('codex','app-server','--listen','stdio://'))
        proc.terminate.assert_called_once();proc.wait.assert_awaited_once()

    async def test_auth_protocol_failure_still_reaps_process(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        from openjarvis.engine._codex_auth import LocalCodexAuth
        proc=SimpleNamespace(returncode=None,stdin=Mock(),stdout=Mock(),terminate=Mock(),kill=Mock(),wait=AsyncMock())
        proc.stdin.drain=AsyncMock();proc.stdout.readline=AsyncMock(return_value=b'')
        with patch('openjarvis.engine._codex_auth.asyncio.create_subprocess_exec',AsyncMock(return_value=proc)):
            with self.assertRaises(ValueError):await LocalCodexAuth()._refresh()
        proc.terminate.assert_called_once();proc.wait.assert_awaited_once()

class LauncherContract(unittest.TestCase):
    def load(self):
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('local_launcher',Path(__file__).resolve().parents[1]/'scripts/launch-local-codex.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def response(self):
        import io
        return io.BytesIO(b'{"model":"codex/gpt-6.1-sol","agent":"simple"}')

    def test_existing_ready_server_opens_native_window_only(self):
        m=self.load()
        with patch.object(m.Path,'is_file',return_value=True), patch.object(m.os,'access',return_value=True), patch.object(m.urllib.request,'urlopen',return_value=self.response()), patch.object(m.subprocess,'run') as run, patch.object(m.subprocess,'Popen') as desktop:
            self.assertEqual(m.main(),0)
        run.assert_not_called()
        desktop.assert_called_once()
        self.assertTrue(desktop.call_args.args[0][0].endswith('/target/release/openjarvis-desktop'))
        self.assertEqual(desktop.call_args.kwargs['env']['OPENJARVIS_DESKTOP_ATTACH_PORT'],'8001')

    def test_start_uses_opt_in_without_inherited_token(self):
        m=self.load()
        with patch.object(m.Path,'is_file',return_value=True), patch.object(m.os,'access',return_value=True), patch.dict(os.environ,{'OPENAI_CODEX_API_KEY':'private sentinel'}), patch.object(m.urllib.request,'urlopen',side_effect=[OSError(),self.response()]), patch.object(m.subprocess,'run',return_value=Mock(returncode=0)) as run, patch.object(m.subprocess,'Popen') as desktop:
            self.assertEqual(m.main(),0)
        args=run.call_args
        self.assertNotIn('OPENAI_CODEX_API_KEY',args.kwargs['env'])
        self.assertNotIn('OPENAI_CODEX_API_KEY',desktop.call_args.kwargs['env'])
        self.assertEqual(args.kwargs['env']['OPENAI_CODEX_USE_LOCAL_AUTH'],'1')
        self.assertNotIn('private sentinel',str(args.args))
        self.assertIn('codex/gpt-6.1-sol',args.args[0])

    def test_failed_start_does_not_open_desktop(self):
        m=self.load()
        with patch.object(m.Path,'is_file',return_value=True), patch.object(m.os,'access',return_value=True), patch.object(m.urllib.request,'urlopen',side_effect=OSError()), patch.object(m.subprocess,'run',return_value=Mock(returncode=1)), patch.object(m.subprocess,'Popen') as desktop, patch('builtins.print'):
            self.assertEqual(m.main(),1)
        desktop.assert_not_called()

    def test_listen_option_starts_native_app_hidden(self):
        m=self.load()
        with patch.object(m.Path,'is_file',return_value=True), patch.object(m.os,'access',return_value=True), patch.object(m.urllib.request,'urlopen',return_value=self.response()), patch.object(m.sys,'argv',['launcher','--listen']), patch.object(m.subprocess,'Popen') as desktop:
            self.assertEqual(m.main(),0)
        self.assertEqual(desktop.call_args.args[0][-1],'--hidden')
        self.assertEqual(desktop.call_args.kwargs['env']['OPENJARVIS_DESKTOP_WAKE'],'1')

    def test_missing_native_binary_does_not_start_server(self):
        m=self.load()
        with patch.object(m.Path,'is_file',return_value=False), patch.object(m.subprocess,'run') as run, patch.object(m.subprocess,'Popen') as desktop, patch('builtins.print'):
            self.assertEqual(m.main(),1)
        run.assert_not_called()
        desktop.assert_not_called()

if __name__=='__main__':unittest.main()
