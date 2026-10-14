#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 native-host/setup.py "$1"
printf '%s\n' 'Installation complete. Reopen the Chrome side panel.'
