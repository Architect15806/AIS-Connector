"""Generate machine-specific native messaging registration files."""
import json
from pathlib import Path
import re
import sys
import os
import shlex

def install(extension_id):
    if not re.fullmatch('[a-p]{32}', extension_id):
        raise ValueError('Invalid Chrome extension ID')
    root = Path(__file__).resolve().parent
    if os.name == 'nt':
        destination = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AISConnector' / 'native-host'
        destination.mkdir(parents=True, exist_ok=True)
        launcher = destination / 'launch.cmd'
        launcher.write_text(f'@echo off\n"{sys.executable}" "{root / "host.py"}"\n', encoding='mbcs')
    elif sys.platform == 'darwin':
        private = Path.home() / 'Library/Application Support/AISConnector/native-host'
        private.mkdir(parents=True, exist_ok=True)
        launcher = private / 'launch.sh'
        launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(root / "host.py"))}\n', encoding='utf-8')
        launcher.chmod(0o700)
        destination = Path.home() / 'Library/Application Support/Google/Chrome/NativeMessagingHosts'
        destination.mkdir(parents=True, exist_ok=True)
    else:
        raise RuntimeError('Only Windows and macOS are supported')
    manifest = {'name':'com.ais.connector', 'description':'AIS Connector native host', 'path':str(launcher), 'type':'stdio', 'allowed_origins':[f'chrome-extension://{extension_id}/']}
    (destination / 'com.ais.connector.json').write_text(json.dumps(manifest), encoding='utf-8')
    print('Native host files installed: ' + str(destination))

if __name__ == '__main__':
    install(sys.argv[1])
