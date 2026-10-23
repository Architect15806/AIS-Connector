import subprocess
import unittest
from unittest.mock import patch
from test_host import host


class SSHDiagnosticsTests(unittest.TestCase):
    def test_gpu_timeout_preserves_ssh(self):
        ok = subprocess.CompletedProcess([], 0, 'remote-host\n', '')
        timeout = subprocess.TimeoutExpired([], 16, stderr=b'Authenticated to localhost\n')
        with patch.object(host, 'ssh_run', side_effect=[ok, timeout]) as run:
            good, detail = host.probe_ssh(1234)
        self.assertTrue(good)
        self.assertEqual(detail['hostname'], 'remote-host')
        self.assertIn('error', detail['gpu'])
        self.assertEqual(run.call_args_list[0].args[1], 'hostname')

    def test_handshake_timeout_does_not_scan(self):
        timeout = subprocess.TimeoutExpired([], 16, stderr=b'debug1: Connection established.\n')
        with patch.object(host, 'ssh_run', side_effect=timeout) as run:
            good, detail = host.probe_ssh(1234)
        self.assertFalse(good)
        self.assertIn('TCP', detail)
        self.assertEqual(run.call_count, 1)

    def test_command_stage_and_redaction(self):
        detail = host.ssh_diagnostic(b'Authenticated to localhost\npassword=secret-value\n', True)
        self.assertNotIn('secret-value', detail)
        self.assertIn('[REDACTED]', detail)

    def test_gpu_nonzero_preserves_ssh(self):
        results = [subprocess.CompletedProcess([], 0, 'remote\n', ''),
                   subprocess.CompletedProcess([], 124, '', 'timeout')]
        with patch.object(host, 'ssh_run', side_effect=results):
            good, detail = host.probe_ssh(1234)
        self.assertTrue(good)
        self.assertIn('error', detail['gpu'])
