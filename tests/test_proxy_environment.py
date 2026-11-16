import unittest
from unittest.mock import patch
from test_host import host


class ProxyEnvironmentTests(unittest.TestCase):
    def test_connect_filters_proxy_variants_without_mutating_parent(self):
        parent = {'PATH': 'original-path', 'HTTP_PROXY': 'http://localhost:1000',
                  'https_proxy': 'http://localhost:2000', 'All_Proxy': 'socks5://localhost:3000',
                  'NO_PROXY': 'localhost', 'CUSTOM_SETTING': 'keep'}
        original = parent.copy()
        with patch.object(host.os, 'environ', parent), patch.object(host.subprocess, 'Popen') as popen:
            host.start_tunnel_process('workflow_123', 'example.user')
            child = popen.call_args.kwargs['env']
            self.assertFalse(any(k.lower() in ('http_proxy', 'https_proxy', 'all_proxy') for k in child))
            self.assertEqual(child['NO_PROXY'], 'localhost')
            self.assertEqual(child['CUSTOM_SETTING'], 'keep')
            self.assertIn(str(host.SSCTL.parent), child['PATH'])
            self.assertEqual(parent, original)

    def test_login_environment_is_unchanged(self):
        with patch.object(host.os, 'environ', {'HTTP_PROXY': 'http://localhost:1000'}):
            self.assertEqual(host.environment('example.user')['HTTP_PROXY'], 'http://localhost:1000')

    def test_connect_without_proxy(self):
        with patch.object(host.os, 'environ', {'PATH': 'original-path'}):
            child = host.environment('example.user', ignore_http_proxy=True)
            self.assertTrue(child['SEASTAR_TOKEN_NAME'].startswith('ais-connector-'))
