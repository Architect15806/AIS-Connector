import re
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path
from test_host import host, HOST


class NamespaceTests(unittest.TestCase):
    def test_formats_across_frontend_profile_catalog_and_connect(self):
        html=(HOST.parents[1]/'extension/panel.html').read_text(encoding='utf-8')
        pattern=re.search(r'id="field2" pattern="([^"]+)"',html).group(1)
        for namespace, valid in [('workflow_123',True),('experiment_12345678_87654321',True),
                                 ('experiment_123',False),('experiment_1_2_3',False),
                                 ('workflow_abc',False),('experiment_1_2;cmd',False)]:
            with self.subTest(namespace=namespace):
                self.assertEqual(bool(re.fullmatch(pattern,namespace)),valid)
                c={'id':str(uuid.uuid4()),'alias':'test','namespace':namespace}
                if not valid:
                    with self.assertRaises(ValueError):host.profile_data({'users':[],'connections':[c]})
                    with self.assertRaises(ValueError):host.publish_agent_connections([c])
                    with patch.object(host,'SSCTL',HOST),patch.object(host,'log_event'):
                        with self.assertRaises(ValueError):host.dispatch({'action':'connect',**c,'loginName':'test'})
                    continue
                self.assertEqual(host.profile_data({'users':[],'connections':[c]})['connections'][0]['namespace'],namespace)
                with patch.object(host,'export_lock',side_effect=RuntimeError('validated catalog')):
                    with self.assertRaisesRegex(RuntimeError,'validated catalog'):host.publish_agent_connections([c])
                with patch.object(host,'SSCTL',HOST),patch.object(host,'log_event'),patch.object(host,'read_state',return_value={'status':'connected','namespace':namespace,'loginName':'test'}):
                    self.assertEqual(host.dispatch({'action':'connect',**c,'loginName':'test'})['namespace'],namespace)
