import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import os
import subprocess
import sys
from test_host import host

class AgentExportTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows byte-range locking')
    def test_export_lock_waits_without_reading_locked_byte(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(host, 'ROOT', Path(folder)):
            with host.export_lock():
                pass
            child = subprocess.Popen([sys.executable, '-u', '-c',
                "import msvcrt,sys,time; f=open(sys.argv[1],'r+b'); msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); print('ready',flush=True); time.sleep(0.5)",
                str(Path(folder)/'agent/export.lock')], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                with host.export_lock():
                    pass
            finally:
                child.wait(timeout=5)
                child.stdout.close()

    def test_export_tracks_port_rename_failure_delete(self):
        identifier = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder, patch.object(host,'ROOT',Path(folder)), patch.object(host,'worker_running',return_value=True):
            catalog=[{'id':identifier,'alias':'示例连接','namespace':'workflow_12345678'}]
            path=Path(host.publish_agent_connections(catalog))
            self.assertEqual(json.loads(path.read_text()),{})
            state={'pid':1,'status':'connected','verified_at':100,'namespace':'workflow_12345678','port':1234}
            host.write_state(identifier,state)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'示例连接':'ssh -p 1234 127.0.0.1'})
            state.update(status='reconnecting')
            host.write_state(identifier,state)
            self.assertEqual(json.loads(path.read_text()),{})
            state.update(status='connected',port=2345)
            host.write_state(identifier,state)
            catalog[0]['alias']='新别名'
            host.publish_agent_connections(catalog)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'新别名':'ssh -p 2345 127.0.0.1'})
            host.dispatch({'action':'stop','id':identifier})
            self.assertEqual(json.loads(path.read_text()),{})
            host.publish_agent_connections([])
            self.assertEqual(json.loads(path.read_text()),{})

    def test_duplicate_alias_rejected_without_overwriting_catalog(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(host,'ROOT',Path(folder)):
            catalog=[{'id':str(uuid.uuid4()),'alias':'same','namespace':'workflow_1'}]
            host.publish_agent_connections(catalog)
            with self.assertRaises(ValueError):
                host.publish_agent_connections(catalog+[{'id':str(uuid.uuid4()),'alias':'same','namespace':'workflow_2'}])
            self.assertEqual(json.loads((Path(folder)/'agent/catalog.json').read_text()),catalog)

    def test_dead_process_and_wrong_namespace_are_not_exported(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(host,'ROOT',Path(folder)):
            identifier=str(uuid.uuid4())
            path=Path(host.publish_agent_connections([{'id':identifier,'alias':'server','namespace':'workflow_1'}]))
            with patch.object(host,'alive',return_value=False):
                host.write_state(identifier,{'pid':1,'status':'connected','verified_at':1,'namespace':'workflow_1','port':1234})
            self.assertEqual(json.loads(path.read_text()),{})
            with patch.object(host,'worker_running',return_value=True):
                host.write_state(identifier,{'pid':1,'status':'connected','verified_at':1,'namespace':'workflow_2','port':1234})
            self.assertEqual(json.loads(path.read_text()),{})
