"""Behavioral tests; display mutations use a fake backend, never the desktop."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from runner import main, supervise
from sessions import Sessions


class Display:
    def __init__(self):
        self.color = 0
        self.events = []
        self.path = None
        self.fail_restore = False
        self.fail_enable = False

    def snapshot(self, connector=None):
        return {'connector': connector or 'DP-3', 'original_color': self.color, 'changed': self.color != 1}

    def enable(self, saved):
        # Simulate a change followed by a lost D-Bus response as well as success.
        self.events.append('enable')
        if self.path is not None:
            assert json.loads(self.path.read_text())['monitors'][saved['connector']]['snapshot']['original_color'] == 0
        self.color = 1
        if self.fail_enable:
            raise RuntimeError('Lost D-Bus reply')

    def restore(self, saved):
        self.events.append('restore')
        if self.fail_restore:
            raise RuntimeError('Monitor unplugged')
        if saved['changed'] and self.color == 1:
            self.color = saved['original_color']


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.display = Display()
        self.sessions = Sessions(self.temp.name, self.display)
        self.display.path = self.sessions.path

    def test_journal_precedes_display_and_normal_exit_restores(self):
        lease = self.sessions.acquire()
        self.assertEqual(self.display.color, 1)
        self.sessions.release(lease)
        self.assertEqual(self.display.color, 0)
        self.assertEqual(json.loads(self.sessions.path.read_text())['monitors'], {})

    def test_overlapping_sessions_restore_only_after_last_exit(self):
        first = self.sessions.acquire()
        # Two distinct supervisor identities, both considered live by this test.
        self.sessions.alive = lambda identity: True
        second_identity = {'pid': 999999, 'start': 'other'}
        with patch('sessions.process_identity', return_value=second_identity):
            second = self.sessions.acquire()
        self.sessions.release(first)
        self.assertEqual(self.display.color, 1)
        self.sessions.release(second)
        self.assertEqual(self.display.color, 0)

    def test_hdr_already_enabled_remains_enabled(self):
        self.display.color = 1
        self.display.path = None
        lease = self.sessions.acquire()
        self.sessions.release(lease)
        self.assertEqual(self.display.color, 1)

    def test_failed_restore_survives_for_retry(self):
        lease = self.sessions.acquire()
        self.display.fail_restore = True
        with self.assertRaisesRegex(RuntimeError, 'unplugged'):
            self.sessions.release(lease)
        self.assertIn('DP-3', json.loads(self.sessions.path.read_text())['monitors'])
        self.display.fail_restore = False
        self.sessions.recover()
        self.assertEqual(self.display.color, 0)

    def test_crashed_supervisor_is_recovered_but_live_one_is_untouched(self):
        lease = self.sessions.acquire()
        self.sessions.recover()
        self.assertEqual(self.display.color, 1)
        self.sessions.alive = lambda identity: False
        self.sessions.recover()
        self.assertEqual(self.display.color, 0)

    def test_lost_enable_reply_rolls_back(self):
        self.display.fail_enable = True
        with self.assertRaisesRegex(RuntimeError, 'Lost D-Bus'):
            self.sessions.acquire()
        self.assertEqual(self.display.color, 0)

    def test_failed_journal_write_prevents_display_mutation(self):
        with patch.object(self.sessions, 'save', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):
                self.sessions.acquire()
        self.assertEqual(self.display.events, [])

    def test_corrupt_journal_is_not_overwritten(self):
        self.sessions.path.write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):
            self.sessions.acquire()
        self.assertEqual(self.display.events, [])
        self.assertEqual(self.sessions.path.read_text(), '{broken')

    def test_exit_code_preserved_and_failure_to_spawn_restores(self):
        self.assertEqual(supervise([sys.executable, '-c', 'raise SystemExit(23)'], sessions=self.sessions), 23)
        self.assertEqual(self.display.color, 0)
        self.assertEqual(supervise(['/missing/proton-command'], sessions=self.sessions), 127)
        self.assertEqual(self.display.color, 0)

    def test_fail_open_and_strict_mode(self):
        self.display.fail_enable = True
        command = [sys.executable, '-c', 'raise SystemExit(23)']
        self.assertEqual(supervise(command, sessions=self.sessions), 23)
        self.assertEqual(supervise(command, sessions=self.sessions, strict=True), 1)


class EntrypointTests(unittest.TestCase):
    def test_recovery_command_uses_the_shared_session_journal(self):
        with patch('runner.Sessions') as sessions:
            self.assertEqual(main(['--recover']), 0)
            sessions.return_value.recover.assert_called_once_with()

    def test_term_is_forwarded_before_restoration(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            events = base / 'events'
            child = base / 'child.py'
            child.write_text('''import signal, sys, time
from pathlib import Path
events = Path(sys.argv[1])
def stop(signum, frame):
    with events.open('a') as stream: stream.write('child terminated\\n')
    raise SystemExit(42)
signal.signal(signal.SIGTERM, stop)
with events.open('a') as stream: stream.write('child ready\\n')
while True: time.sleep(0.1)
''')
            harness = base / 'harness.py'
            harness.write_text('''import sys
from pathlib import Path
from runner import supervise
events = Path(sys.argv[1])
class Sessions:
    def acquire(self, monitor): return ('DP-3', {})
    def release(self, lease):
        with events.open('a') as stream: stream.write('restored\\n')
raise SystemExit(supervise([sys.executable, sys.argv[2], str(events)], sessions=Sessions()))
''')
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
            process = subprocess.Popen([sys.executable, str(harness), str(events), str(child)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(lambda: process.kill() if process.poll() is None else None)
            deadline = time.monotonic() + 5
            while not events.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(events.exists(), 'Child failed to start')
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=5), 42)
            self.assertEqual(events.read_text().splitlines(), ['child ready', 'child terminated', 'restored'])


if __name__ == '__main__':
    unittest.main()
