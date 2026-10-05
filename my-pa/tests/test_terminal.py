import copy
import io
from contextlib import redirect_stdout, redirect_stderr
import unittest
from unittest.mock import patch
from mypa.cli import main, answer
from mypa.config import DEFAULTS
from mypa.terminal import Terminal, clean


class TerminalTests(unittest.TestCase):
    def test_plain_header_and_help(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()), patch('builtins.input', side_effect=['/help', '/tools', '/exit']):
            main([])
        self.assertIn('LOCAL AGENT', output.getvalue())
        self.assertIn('/paste', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())

    def test_workspace_flags_before_and_after_agent(self):
        for arguments in [['--workspace', '/tmp'], ['agent', '--workspace', '/tmp'], ['--workspace', '/tmp', 'agent']]:
            with patch('mypa.cli.cmd_chat') as start:
                main(arguments)
            self.assertEqual(start.call_args.args[0].workspace, '/tmp')

    def test_final_reply_replaces_preliminary_model_claim(self):
        def fake_run(cfg, messages, on_event, use_tools):
            on_event({'type':'token','text':'I created it'})
            on_event({'type':'reset'})
            return {'reply':'No completion verified', 'trace':[]}
        output = io.StringIO()
        with patch('mypa.agent.run', side_effect=fake_run), redirect_stdout(output), redirect_stderr(io.StringIO()):
            answer(copy.deepcopy(DEFAULTS), [{'role':'user','content':'Create a file'}], stream=True)
        self.assertNotIn('I created it', output.getvalue())
        self.assertIn('No completion verified', output.getvalue())

    def test_terminal_controls_are_removed_from_untrusted_output(self):
        self.assertEqual(clean('\x1b[2Jhello\x1b]0;title\x07\nworld'), 'hello\nworld')

    def test_error_does_not_end_interactive_session(self):
        output = io.StringIO()
        with patch('mypa.cli.answer', side_effect=RuntimeError('offline')), patch('builtins.input', side_effect=['Hello', '/status', '/exit']), redirect_stdout(output), redirect_stderr(io.StringIO()):
            main([])
        self.assertEqual(output.getvalue().count('LOCAL AGENT'), 2)

    def test_paste_passes_multiline_request(self):
        with patch('mypa.cli.answer', return_value='Done') as call, patch('builtins.input', side_effect=['/paste','line one','line two','.','/exit']), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            main([])
        self.assertEqual(call.call_args.args[1][0]['content'], 'line one\nline two')
