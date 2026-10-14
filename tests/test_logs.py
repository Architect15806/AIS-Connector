import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from test_host import host


class LogTests(unittest.TestCase):
    def test_events_are_sanitized_bounded_and_read_newest_first(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            host.log_event('test', token='DO-NOT-STORE', password='DO-NOT-STORE',
                           error='token=secret-value Bearer bearer-value at_secret 123456')
            rows = host.read_logs()
            text = json.dumps(rows)
            for secret in ('DO-NOT-STORE', 'secret-value', 'bearer-value', 'at_secret', '123456'):
                self.assertNotIn(secret, text)
            db = host.log_database()
            with db:
                db.executemany('INSERT INTO events(timestamp,level,event,details) VALUES(?,?,?,?)',
                               [(1, 'info', 'test', '{}')] * 2050)
            db.close()
            host.log_event('last')
            db = host.log_database()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2000)
            db.close()
            self.assertEqual(len(host.read_logs()), 200)
            self.assertEqual(host.read_logs()[0]['event'], 'last')

    def test_failed_login_does_not_store_auth_output(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            with patch.object(host, 'dispatch_request', side_effect=ValueError('credential TOP-SECRET')):
                with self.assertRaises(ValueError):
                    host.dispatch({'action': 'login', 'token': '123456', 'loginName': 'example.user'})
            events = host.read_logs()
            self.assertEqual(events[0]['event'], 'operation.failed')
            self.assertNotIn('TOP-SECRET', json.dumps(events))
            self.assertNotIn('123456', json.dumps(events))

    def test_paths_and_legacy_snapshot_deduplication(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            info = host.dispatch({'action': 'agent_info'})
            self.assertEqual(info['agent_file'], str(Path(folder)/'agent/connections.json'))
            self.assertTrue(Path(info['skill_file']).is_file())
            identifier = str(uuid.uuid4())
            (Path(folder)/(identifier+'.json')).write_text(json.dumps({'status': 'stopped', 'updated_at': 1}))
            first = host.dispatch({'action': 'logs'})
            second = host.dispatch({'action': 'logs'})
            self.assertEqual(len(first['entries']), 1)
            self.assertEqual(first['entries'], second['entries'])
            self.assertTrue(Path(first['log_file']).is_file())

    def test_log_storage_failure_does_not_break_operations(self):
        with patch.object(host, 'log_database', side_effect=PermissionError('denied')):
            host.log_event('test')
