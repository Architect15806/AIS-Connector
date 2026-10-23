import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_host import host

class WorkerIdentityTests(unittest.TestCase):
    def test_reused_live_pid_with_unlocked_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state.json'
            path.with_suffix('.lock').touch()
            path.write_text(json.dumps({'pid':os.getpid(), 'status':'connected', 'verified_at':1, 'ssh_command':'ssh -p 1234 127.0.0.1'}))
            self.assertTrue(host.alive(os.getpid()))
            state=host.read_state(path)
            self.assertEqual(state['status'],'error')
            self.assertNotIn('ssh_command',state)
            self.assertNotIn('verified_at',state)

    def test_missing_lock_rejects_live_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(host.worker_running(Path(folder)/'state.json',{'pid':os.getpid()}))

    def test_live_worker_lock_then_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.json'
            code="""import os,sys
f=open(sys.argv[1],'a+b')
if os.name=='nt':
 import msvcrt
 msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
print('ready',flush=True)
sys.stdin.readline()
"""
            child=subprocess.Popen([sys.executable,'-u','-c',code,str(path.with_suffix('.lock'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                self.assertTrue(host.worker_running(path,{'pid':child.pid}))
                child.communicate('\n',timeout=5)
                # Even if an unrelated process reuses the PID, the released lock rules it out.
                with patch.object(host,'alive',return_value=True):
                    self.assertFalse(host.worker_running(path,{'pid':child.pid}))
            finally:
                if child.poll() is None:
                    child.kill();child.wait()
                child.stdin.close();child.stdout.close()
