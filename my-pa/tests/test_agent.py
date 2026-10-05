import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from mypa.agent import ToolBox, run, text_tool_calls, compact_history
from mypa.config import DEFAULTS

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg['agent']['workspace'] = self.temp.name
        self.box = ToolBox(self.cfg)
    def tearDown(self): self.temp.cleanup()
    def test_write_read_edit_search(self):
        self.box.execute('write_file', {'path':'src/hello.py','content':'print("hello")\n'})
        self.box.execute('edit_file', {'path':'src/hello.py','old':'hello','new':'world'})
        self.assertEqual(self.box.execute('read_file', {'path':'src/hello.py'}), 'print("world")\n')
        self.assertIn('src/hello.py:1', self.box.execute('search_files', {'query':'world'}))
        with self.assertRaises(ValueError): self.box.execute('edit_file', {'path':'src/hello.py','old':'missing','new':'x'})
    def test_traversal_symlink_and_rules(self):
        with self.assertRaises(ValueError): self.box.path('../escape')
        with self.assertRaises(ValueError): self.box.path('.git/config')
        (Path(self.temp.name)/'outside').symlink_to('/tmp')
        with self.assertRaises(ValueError): self.box.path('outside/escape')
        self.cfg['permissions'] = [{'action':'write','resource':'*','effect':'deny'}]
        with self.assertRaises(ValueError): self.box.execute('write_file', {'path':'a','content':'b'})
    def test_shell_disabled(self):
        self.cfg['agent']['shell_enabled'] = False
        with self.assertRaises(ValueError): self.box.execute('run_command', {'command':'echo hi'})
    def test_model_receives_real_tool_result(self):
        first = Mock(); first.json.return_value = {'message': {'role':'assistant','content':'','tool_calls':[{'function':{'name':'write_file','arguments':{'path':'answer.txt','content':'42'}}}]}}
        second = Mock(); second.json.return_value = {'message': {'role':'assistant','content':'Saved answer.txt'}}
        with patch('mypa.agent.requests.post', side_effect=[first, second]) as post:
            result = run(self.cfg, [{'role':'user','content':'Save the answer'}])
        self.assertEqual((Path(self.temp.name)/'answer.txt').read_text(), '42')
        self.assertTrue(result['trace'][0]['ok'])
        self.assertEqual(post.call_args.kwargs['json']['messages'][-1]['role'], 'tool')
    def test_bad_tool_and_limit(self):
        self.cfg['agent']['max_steps'] = 1
        response = Mock(); response.json.return_value = {'message':{'role':'assistant','content':'','tool_calls':[{'function':{'name':'invalid','arguments':{}}}]}}
        with patch('mypa.agent.requests.post', return_value=response): result = run(self.cfg, [{'role':'user','content':'Do something'}])
        self.assertFalse(result['trace'][0]['ok'])
        self.assertIn('step limit', result['reply'])

    def test_text_tool_call_recovers_after_failed_command(self):
        responses = []
        for message in [
            {'role':'assistant', 'tool_calls':[{'function':{'name':'run_command','arguments':{'command':'failed install'}}}]},
            {'role':'assistant', 'content':'I will retry:\n{"name":"run_command","parameters":{"command":".venv/bin/python -m pip install example"}}'},
            {'role':'assistant', 'content':'Completed after retry'}
        ]:
            response = Mock(); response.json.return_value = {'message': message}; responses.append(response)
        with patch('mypa.agent.requests.post', side_effect=responses), patch.object(ToolBox, 'execute', side_effect=['Exit code: 1\nexternally-managed-environment', 'Exit code: 0\nInstalled']) as execute:
            result = run(self.cfg, [{'role':'user','content':'Install project dependencies'}])
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(result['trace'][0]['ok'])
        self.assertTrue(result['trace'][1]['ok'])
        self.assertEqual(result['reply'], 'Completed after retry')
        self.assertEqual(result['trace'][1]['arguments']['command'], '.venv/bin/python -m pip install example')

    def test_text_parser_ignores_other_json(self):
        self.assertEqual(text_tool_calls('Example {"name":"unknown","parameters":{}}'), [])
        self.assertEqual(text_tool_calls('No tool call'), [])
        self.assertEqual(len(text_tool_calls('```json\n{"function":{"name":"read_file","arguments":{"path":"a"}}}\n```')), 1)

    def test_explicit_project_path_selects_workspace(self):
        response = Mock(); response.json.return_value = {'message':{'role':'assistant','content':'Ready'}}
        with tempfile.TemporaryDirectory() as target, patch('mypa.agent.requests.post', return_value=response):
            result = run(self.cfg, [{'role':'user','content':target + ' inspect this project'}])
            self.assertEqual(result['workspace'], target)

    def test_project_venv_used_for_commands(self):
        import sys
        binaries = Path(self.temp.name) / '.venv' / 'bin'
        binaries.mkdir(parents=True)
        (binaries / 'python').symlink_to(sys.executable)
        result = self.box.execute('run_command', {'command':"python -c 'import os; print(os.environ.get(\"VIRTUAL_ENV\"))'"})
        self.assertIn('Exit code: 0', result)
        self.assertIn(str(binaries.parent), result)

    def test_streamed_quick_chat_and_resource_cleanup(self):
        response = Mock()
        response.iter_lines.return_value = [b'{"message":{"content":"Hello"},"done":false}', b'{"message":{"content":" there"},"done":true}']
        events = []
        with patch('mypa.agent.requests.post', return_value=response) as post:
            result = run(self.cfg, [{'role':'user','content':'Hello'}], on_event=events.append, use_tools=False)
        self.assertEqual(result['reply'], 'Hello there')
        self.assertEqual([e['text'] for e in events if e['type'] == 'token'], ['Hello', ' there'])
        self.assertNotIn('tools', post.call_args.kwargs['json'])
        response.close.assert_called_once()

    def test_streamed_agent_tool_activity(self):
        first = Mock(); first.iter_lines.return_value = [b'{"message":{"tool_calls":[{"function":{"name":"write_file","arguments":{"path":"stream.txt","content":"ok"}}}]},"done":true}']
        second = Mock(); second.iter_lines.return_value = [b'{"message":{"content":"Saved"},"done":true}']
        events = []
        with patch('mypa.agent.requests.post', side_effect=[first, second]):
            result = run(self.cfg, [{'role':'user','content':'Save a file'}], on_event=events.append)
        self.assertEqual(result['reply'], 'Saved')
        self.assertTrue(next(e for e in events if e['type'] == 'tool')['event']['ok'])
        self.assertIn({'type':'reset'}, events)

    def test_incomplete_stream_is_error(self):
        response = Mock(); response.iter_lines.return_value = [b'{"message":{"content":"partial"},"done":false}']
        with patch('mypa.agent.requests.post', return_value=response), self.assertRaises(RuntimeError):
            run(self.cfg, [{'role':'user','content':'Hello'}], on_event=lambda e: None)
        response.close.assert_called_once()

    def test_agent_greeting_avoids_tools(self):
        response = Mock(); response.json.return_value = {'message': {'content':'Hello'}}
        with patch('mypa.agent.requests.post', return_value=response) as post:
            result = run(self.cfg, [{'role':'user','content':'Hi'}])
        self.assertEqual(result['reply'], 'Hello')
        self.assertNotIn('tools', post.call_args.kwargs['json'])

    def test_cli_prints_tokens_without_duplicating_answer(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from mypa.cli import answer
        def fake_run(cfg, messages, on_event, use_tools):
            on_event({'type':'token','text':'Hello'})
            return {'reply':'Hello','trace':[]}
        output = io.StringIO()
        with patch('mypa.agent.run', side_effect=fake_run), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(answer(self.cfg, [{'role':'user','content':'Hi'}], agent=True, stream=True), 'Hello')
        self.assertEqual(output.getvalue().count('Hello'), 1)

    def test_agent_identity_describes_real_capabilities(self):
        response = Mock(); response.json.return_value = {'message': {'content':'I can edit workspace files using tools.'}}
        with patch('mypa.agent.requests.post', return_value=response) as post:
            run(self.cfg, [{'role':'user','content':'Can you change files and folders?'}])
        prompt = post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('You CAN list, read, create and edit files', prompt)
        self.assertIn('HTML, CSS and JavaScript', prompt)
        self.assertIn('tools', post.call_args.kwargs['json'])

    def test_directory_move_and_delete_lifecycle(self):
        self.box.execute('create_directory', {'path': 'work/nested'})
        self.box.execute('write_file', {'path': 'work/nested/a.txt', 'content': 'before'})
        self.box.execute('edit_file', {'path': 'work/nested/a.txt', 'old': 'before', 'new': 'after'})
        self.box.execute('move_path', {'path': 'work', 'destination': 'done'})
        self.assertEqual((Path(self.temp.name)/'done/nested/a.txt').read_text(), 'after')
        with self.assertRaises(OSError):
            self.box.execute('delete_path', {'path': 'done', 'recursive': 'false'})
        self.box.execute('delete_path', {'path': 'done', 'recursive': 'true'})
        self.assertFalse((Path(self.temp.name)/'done').exists())

    def test_destructive_tools_protect_root_and_nested_metadata(self):
        with self.assertRaises(ValueError):
            self.box.execute('delete_path', {'path': '.', 'recursive': 'true'})
        (Path(self.temp.name)/'project/.git').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.box.execute('delete_path', {'path': 'project', 'recursive': 'true'})
        with self.assertRaises(ValueError):
            self.box.execute('move_path', {'path': 'project', 'destination': 'new'})

    def test_move_checks_permissions_at_both_paths(self):
        self.box.execute('write_file', {'path': 'a', 'content': 'data'})
        for rules in [
            [{'action':'write', 'resource':'a', 'effect':'deny'}, {'action':'write', 'resource':'b', 'effect':'allow'}],
            [{'action':'write', 'resource':'b', 'effect':'deny'}],
        ]:
            self.cfg['permissions'] = rules
            with self.assertRaises(ValueError): self.box.execute('move_path', {'path':'a', 'destination':'b'})
        self.cfg['permissions'] = [{'action':'delete', 'resource':'*', 'effect':'deny'}]
        with self.assertRaises(ValueError): self.box.execute('delete_path', {'path':'a', 'recursive':'false'})

    def test_unexecuted_action_retries_instead_of_claiming_done(self):
        responses = []
        for message in [
            {'content': 'Created the file.'},
            {'tool_calls': [{'function': {'name': 'write_file', 'arguments': {'path':'real.txt', 'content':'yes'}}}]},
            {'content': 'Saved real.txt.'},
        ]:
            response = Mock(); response.json.return_value = {'message':message}; responses.append(response)
        with patch('mypa.agent.requests.post', side_effect=responses):
            result = run(self.cfg, [{'role':'user','content':'Create real.txt'}])
        self.assertEqual((Path(self.temp.name)/'real.txt').read_text(), 'yes')
        self.assertTrue(result['trace'][0]['ok'])

    def test_no_execution_is_reported_honestly(self):
        response = Mock(); response.json.return_value = {'message': {'content':'Done'}}
        events = []
        with patch('mypa.agent.requests.post', return_value=response) as post:
            result = run(self.cfg, [{'role':'user','content':'Delete missing.txt'}])
        self.assertEqual(post.call_count, 3)
        self.assertIn('No completion is verified', result['reply'])
        self.assertEqual(result['trace'], [])

    def test_search_http_failure_uses_fallback_and_closes_responses(self):
        import requests
        first = Mock(); first.raise_for_status.side_effect = requests.HTTPError('blocked')
        second = Mock(); second.content = b'<rss><channel><item><title>Python docs</title><link>https://docs.python.org/3/</link><description>Python</description></item></channel></rss>'
        with patch('mypa.agent.requests.get', side_effect=[first, second]):
            result = self.box.execute('web_search', {'query':'Python docs'})
        self.assertIn('https://docs.python.org/3/', result)
        first.close.assert_called_once(); second.close.assert_called_once()

    def test_compaction_keeps_request_and_matching_tool_call(self):
        request = {'role':'user','content':'Create a project'}
        call = {'role':'assistant','tool_calls':[{'function':{'name':'read_file','arguments':{'path':'a'}}}]}
        history = [{'role':'system','content':'instructions'}, request,
                   {'role':'assistant','content':'x'*25000}, call,
                   {'role':'tool','tool_name':'read_file','content':'z'*16000}]
        compact = compact_history(history, request=request)
        self.assertIn(request, compact)
        self.assertIn(call, compact)
        self.assertEqual(compact[-1]['role'], 'tool')
        self.assertLess(len(compact[-1]['content']), 6500)
