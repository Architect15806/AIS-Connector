import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('setup_host', Path(__file__).resolve().parents[1] / 'native-host/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

class MacSetupTests(unittest.TestCase):
    def test_mac_registration_and_quoted_launcher(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'project with spaces'
            root.mkdir()
            with patch.object(setup, '__file__', str(root/'setup.py')), patch.object(setup, 'os', SimpleNamespace(name='posix')), patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.Path, 'home', return_value=Path(folder)):
                setup.install('a'*32)
            manifest=json.loads((Path(folder)/'Library/Application Support/Google/Chrome/NativeMessagingHosts/com.ais.connector.json').read_text())
            self.assertEqual(manifest['allowed_origins'], ['chrome-extension://'+'a'*32+'/'])
            private=Path(folder)/'Library/Application Support/AISConnector/native-host'
            self.assertEqual(manifest['path'], str(private/'launch.sh'))
            launcher=(private/'launch.sh').read_text()
            self.assertTrue(launcher.startswith('#!/bin/sh\nexec '))
            self.assertIn("'"+str(root/'host.py')+"'", launcher)

