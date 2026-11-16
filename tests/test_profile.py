import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('profile_host', Path(__file__).resolve().parents[1] / 'native-host/host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

class ProfileTests(unittest.TestCase):
    def test_connection_enabled_persists_and_defaults_true(self):
        connection={'id':str(uuid.uuid4()),'alias':'test','namespace':'workflow_123'}
        profile={'users':[],'connections':[connection]}
        self.assertTrue(host.profile_data(profile)['connections'][0]['enabled'])
        connection['enabled']=False
        self.assertFalse(host.profile_data(profile)['connections'][0]['enabled'])
    def test_migration_is_durable_idempotent_and_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            uid, cid = str(uuid.uuid4()), str(uuid.uuid4())
            profile = {'users': [{'id': uid, 'name': 'example.user', 'token': 'secret'}],
                       'selected': uid, 'connections': [{'id': cid, 'alias': 'Example', 'namespace': 'workflow_123', 'userId': uid}], 'token': 'secret'}
            self.assertIsNone(host.dispatch({'action': 'profile_get'})['profile'])
            first = host.dispatch({'action': 'profile_init', 'profile': profile})['profile']
            second = host.dispatch({'action': 'profile_init', 'profile': {'users': [], 'connections': []}})['profile']
            self.assertEqual(first, second)
            text = (Path(folder) / 'profile.json').read_text()
            self.assertNotIn('secret', text)
            self.assertNotIn('userId', text)
            self.assertEqual(json.loads(text)['connections'][0]['id'], cid)
            with self.assertRaises(ValueError):
                host.dispatch({'action': 'profile_save', 'profile': {'users': [{'id': uid, 'name': 'invalid name'}]}})
            self.assertEqual((Path(folder) / 'profile.json').read_text(), text)
