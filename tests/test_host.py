import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import itertools
from unittest.mock import MagicMock

HOST = Path(__file__).resolve().parents[1] / 'native-host' / 'host.py'
spec = importlib.util.spec_from_file_location('host', HOST)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

class HostTests(unittest.TestCase):
    def test_monitor_rebuilds_failed_tunnel_and_preserves_refresh_time(self):
        identifier = str(uuid.uuid4())
        probes = []
        snapshots = []
        stop = MagicMock()
        stop.exists.side_effect = lambda: len(probes) >= 5
        processes = []
        for port in (1234, 2345):
            proc = MagicMock()
            proc.poll.return_value = None
            proc.stdout.read1.side_effect = [f'ssh -p {port} 127.0.0.1'.encode(), b'']
            processes.append(proc)
        def probe(port):
            probes.append(port)
            return (False, 'banner timeout') if len(probes) == 3 else (True, 'remote-host')
        def thread(**kwargs):
            obj = MagicMock()
            obj.start.side_effect = kwargs['target']
            return obj
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)), patch.object(host, 'settings', return_value={'interval_minutes':0.1}), patch.object(host, 'start_tunnel_process', side_effect=processes) as start, patch.object(host, 'probe_ssh', side_effect=probe), patch.object(host, 'close_tunnel'), patch.object(host.threading, 'Thread', side_effect=thread), patch.object(host.time, 'sleep'), patch.object(host.time, 'monotonic', side_effect=itertools.count(0,10)), patch.object(host.time, 'time', side_effect=itertools.count(1000)), patch.object(host, 'write_state', side_effect=lambda i,s: snapshots.append(dict(s))):
            host.monitor(identifier, 'workflow_12345678', 'user', stop, {'status':'connecting'})
        connected = [s for s in snapshots if s['status']=='connected' and not s.get('probe_running')]
        self.assertEqual(start.call_count, 2)
        self.assertEqual(connected[0]['port_refreshed_at'], connected[1]['port_refreshed_at'])
        self.assertGreater(connected[2]['port_refreshed_at'], connected[1]['port_refreshed_at'])
        self.assertEqual(connected[2]['ssh_command'], 'ssh -p 2345 127.0.0.1')
        self.assertTrue(any(s['status']=='reconnecting' and 'ssh_command' not in s for s in snapshots))

    def test_settings_persist_and_reject_invalid_intervals(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            self.assertEqual(host.settings()['interval_minutes'],5)
            host.dispatch({'action':'settings','interval_minutes':2.5})
            self.assertEqual(host.settings()['interval_minutes'],2.5)
            self.assertNotIn('settings',host.dispatch({'action':'status'})['connections'])
            for value in (0, -1, True, '5', 1441, float('nan')):
                with self.assertRaises(ValueError):
                    host.dispatch({'action':'settings','interval_minutes':value})

    def test_countdown_resets_at_start(self):
        state={}
        with patch.object(host.time,'time',return_value=1000):
            host.reset_countdown(state,120)
        self.assertEqual(state['countdown_started_at'],1000)
        self.assertEqual(state['next_check_at'],1120)
        with patch.object(host.time,'time',return_value=1020):
            host.reset_countdown(state,60)
        self.assertEqual(state['next_check_at'],1080)

    def test_settings_requests_immediate_check_for_active_only(self):
        running,stopped=str(uuid.uuid4()),str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder,patch.object(host,'ROOT',Path(folder)),patch.object(host,'worker_running',return_value=True):
            host.write_state(running,{'status':'connected','pid':1,'verified_at':100})
            host.write_state(stopped,{'status':'stopped'})
            host.dispatch({'action':'settings','interval_minutes':3})
            self.assertTrue((Path(folder)/(running+'.check')).exists())
            self.assertFalse((Path(folder)/(stopped+'.check')).exists())

    def test_tunnel_keeps_stdin_open(self):
        with patch.object(host.subprocess, 'Popen') as popen:
            process = host.start_tunnel_process('workflow_12345678', 'example.user')
            self.assertEqual(popen.call_args.kwargs['stdin'], subprocess.PIPE)
            self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.PIPE)
            self.assertFalse(popen.call_args.kwargs.get('shell', False))
            process.communicate.assert_not_called()
            process.stdin.close.assert_not_called()

    def test_listening_port_does_not_imply_ssh_success(self):
        with patch.object(host.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, '', 'Connection timed out during banner exchange')):
            good, detail = host.probe_ssh(13903)
        self.assertFalse(good)
        self.assertIn('banner exchange', detail)

    def test_ssh_success_requires_remote_command(self):
        with patch.object(host.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'test-host\n', '')) as run:
            good, detail = host.probe_ssh(13903)
            self.assertTrue(good)
            self.assertEqual(detail['hostname'], 'test-host')
            self.assertIn('error', detail['gpu'])
        self.assertIn('nvidia-smi -q -x', run.call_args.args[0][-1])

    def test_old_unverified_state_is_not_connected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'worker_running', return_value=True):
            path = Path(folder) / 'state.json'
            path.write_text(json.dumps({'pid':1, 'status':'connected'}))
            self.assertEqual(host.read_state(path)['status'], 'degraded')

    def test_native_message_transport(self):
        data = json.dumps({'action': 'status'}).encode()
        result = subprocess.run([sys.executable, str(HOST)], input=struct.pack('<I', len(data))+data, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        length = struct.unpack('<I', result.stdout[:4])[0]
        self.assertEqual(length, len(result.stdout)-4)
        self.assertTrue(json.loads(result.stdout[4:])['ok'])

    def test_login_noninteractive_and_errors_redacted(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)), patch.object(host, 'SSCTL', HOST), patch.object(host.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, '', 'failed 123456 at_secret eyJabc.xyz')
            with self.assertRaises(ValueError) as error:
                host.dispatch({'action':'login', 'loginName':'example.user', 'token':'123456'})
            self.assertNotIn('123456', str(error.exception))
            self.assertNotIn('at_secret', str(error.exception))
            self.assertEqual(run.call_args.args[0][-2:], ['-alilang-token', '123456'])
            self.assertNotIn('-ant-family-token-stdin', run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    @unittest.skipUnless(host.SSCTL.is_file(), 'Local ssctl is not installed')
    def test_installed_ssctl_accepts_token_without_tty(self):
        # Generate a request only; never contact the authentication service.
        result = subprocess.run([str(host.SSCTL), 'login', '-login-name', 'diagnostic',
                                 '-alilang-token', '000000', '-addr', 'http://127.0.0.1:1',
                                 '-output-curl-string'], stdin=subprocess.DEVNULL,
                                capture_output=True, encoding='utf-8', errors='replace',
                                creationflags=host.NO_WINDOW, timeout=15)
        self.assertEqual(result.returncode, 0, host.clean(result.stderr))
        self.assertIn('ampw_antlogin:authenticate', result.stdout)
        self.assertNotIn('The handle is invalid', result.stderr)

    def test_user_credentials_are_isolated(self):
        with patch.dict(host.os.environ, {'SEASTAR_TOKEN':'secret'}):
            one, two = host.environment('one'), host.environment('two')
        self.assertNotEqual(one['SEASTAR_TOKEN_NAME'], two['SEASTAR_TOKEN_NAME'])
        self.assertNotIn('SEASTAR_TOKEN', one)

    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            host.state_path('../../x')

    def test_fragmented_input(self):
        class Fragmented(io.BytesIO):
            def read(self, n):
                return super().read(min(n, 2))
        self.assertEqual(host.read_exact(Fragmented(b'abcdef'), 6), b'abcdef')

    def test_tunnel_survives_native_host_exit(self):
        # The supervisor has no browser stdin/stdout handles and uses detached mode.
        identifier = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)), patch.object(host, 'SSCTL', HOST), patch.object(host.subprocess, 'Popen') as popen, patch.object(host, 'read_state', side_effect=[{'status':'stopped'}, {'status':'connecting'}]):
            host.dispatch({'action':'connect','id':identifier,'namespace':'workflow_12345678','loginName':'example.user'})
            kwargs = popen.call_args.kwargs
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            self.assertTrue(kwargs['creationflags'] & subprocess.DETACHED_PROCESS)

if __name__ == '__main__':
    unittest.main()
