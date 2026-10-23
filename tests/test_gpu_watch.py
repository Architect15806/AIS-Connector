import itertools
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch
from test_host import host

class WatchTests(unittest.TestCase):
    def test_toggle_requires_upgraded_connected_worker(self):
        identifier=str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as folder, patch.object(host,'ROOT',Path(folder)):
            with patch.object(host,'read_state',return_value={'status':'connected','monitor_version':2}):
                with self.assertRaises(ValueError):
                    host.dispatch({'action':'gpu_watch','id':identifier,'enabled':True})
            with patch.object(host,'read_state',return_value={'status':'connected','monitor_version':3}):
                host.dispatch({'action':'gpu_watch','id':identifier,'enabled':True})
                self.assertTrue((Path(folder)/(identifier+'.watch')).exists())
                host.dispatch({'action':'gpu_watch','id':identifier,'enabled':False})
                self.assertFalse((Path(folder)/(identifier+'.watch')).exists())

    def test_watch_failure_does_not_reconnect_or_reset_regular_countdown(self):
        identifier=str(uuid.uuid4());calls=[];snapshots=[]
        stop=MagicMock();stop.exists.side_effect=lambda:len(calls)>=3
        proc=MagicMock();proc.poll.return_value=None
        proc.stdout.read1.side_effect=[b'ssh -p 1234 127.0.0.1',b'']
        def thread(**kwargs):
            t=MagicMock();t.start.side_effect=kwargs['target'];return t
        def probe(port):
            calls.append(port)
            return (False,'watch timeout') if len(calls)==2 else (True,{'hostname':'test','gpu':{'cards':[]}})
        with tempfile.TemporaryDirectory() as folder, patch.object(host,'ROOT',Path(folder)), patch.object(host,'settings',return_value={'interval_minutes':5}), patch.object(host,'start_tunnel_process',return_value=proc) as start, patch.object(host,'close_tunnel'), patch.object(host.threading,'Thread',side_effect=thread), patch.object(host,'probe_ssh',side_effect=probe), patch.object(host.time,'sleep'), patch.object(host.time,'monotonic',side_effect=itertools.count(0,.25)), patch.object(host,'write_state',side_effect=lambda i,s:snapshots.append(json.loads(json.dumps(s)))):
            (Path(folder)/(identifier+'.watch')).touch()
            host.monitor(identifier,'workflow_123','example.user',stop,{'status':'connecting'})
            self.assertFalse((Path(folder)/(identifier+'.watch')).exists())
        self.assertEqual(start.call_count,1)
        connected=[s for s in snapshots if s['status']=='connected']
        self.assertTrue(any(s.get('gpu',{}).get('error')=='watch timeout' for s in connected))
        self.assertEqual(len({s['countdown_started_at'] for s in connected}),1)
        self.assertEqual(len({s['port_refreshed_at'] for s in connected}),1)
