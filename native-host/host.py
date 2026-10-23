"""Chrome native messaging host and detached ssctl tunnel supervisor (stdlib only)."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import sqlite3
import importlib.util
import xml.etree.ElementTree as ET
from contextlib import contextmanager

ROOT = (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AISConnector'
        if os.name == 'nt' else Path.home() / 'Library' / 'Application Support' / 'AISConnector')
SSCTL = Path.home() / '.ssctl' / 'bin' / ('ssctl.exe' if os.name == 'nt' else 'ssctl')
if not SSCTL.exists() and shutil.which('ssctl'):
    SSCTL = Path(shutil.which('ssctl'))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ACTIVE = ('connecting', 'checking', 'connected', 'degraded', 'reconnecting')

def log_database():
    directory = ROOT / 'logs'
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(directory / 'events.sqlite3'), timeout=2)
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, timestamp REAL, level TEXT, event TEXT, details TEXT)')
    return db

def log_event(event, level='info', **fields):
    # Fixed field allowlist: never serialize requests, profiles, tokens or environment.
    allowed = {'id', 'namespace', 'loginName', 'status', 'port', 'probe_running', 'error', 'action'}
    details = {k: clean(str(v)) for k, v in fields.items() if k in allowed and v is not None}
    try:
        db = log_database()
        try:
            with db:
                db.execute('INSERT INTO events(timestamp,level,event,details) VALUES(?,?,?,?)',
                           (time.time(), level, event, json.dumps(details, ensure_ascii=False)))
                db.execute('DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-2000 FROM events)')
        finally:
            db.close()
    except (OSError, sqlite3.Error):
        pass  # Diagnostics must never interrupt a working tunnel.

def read_logs():
    db = log_database()
    try:
        rows = db.execute('SELECT id,timestamp,level,event,details FROM events ORDER BY id DESC LIMIT 200').fetchall()
    finally:
        db.close()
    return [{'id': r[0], 'timestamp': r[1], 'level': r[2], 'event': r[3], 'details': json.loads(r[4])} for r in rows]

def log_snapshots():
    """Capture older workers' current state without restarting their tunnels."""
    db = log_database()
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, fingerprint TEXT)')
            for path in ROOT.glob('*.json'):
                try:
                    identifier = validate_id(path.stem)
                except ValueError:
                    continue
                state = read_state(path)
                fields = {k: clean(str(state[k])) for k in ('namespace', 'loginName', 'status', 'port', 'error', 'updated_at') if k in state}
                detail = json.dumps({'id': identifier, **fields}, ensure_ascii=False)
                previous = db.execute('SELECT fingerprint FROM snapshots WHERE id=?', (identifier,)).fetchone()
                fingerprint = hashlib.sha256(detail.encode()).hexdigest()
                if previous and previous[0] == fingerprint:
                    continue
                db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?)', (identifier, fingerprint))
                db.execute('INSERT INTO events(timestamp,level,event,details) VALUES(?,?,?,?)',
                           (time.time(), 'error' if state.get('error') else 'info', 'connection.snapshot', detail))
            db.execute('DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id),0)-2000 FROM events)')
    finally:
        db.close()

@contextmanager
def export_lock():
    directory = ROOT / 'agent'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'export.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            # Windows byte-range locks also forbid reads by another process.
            # Inspect metadata, not the locked byte, before acquiring the lock.
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b'0')
                lock.flush()
            for attempt in range(100):
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 99:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def atomic_json(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(text, encoding='utf-8')
        for attempt in range(20):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        temp.unlink(missing_ok=True)

def publish_agent_connections(catalog=None):
    if catalog is not None:
        if not isinstance(catalog, list) or len(catalog) > 1000:
            raise ValueError('Invalid connection catalog')
        entries, names, ids = [], set(), set()
        for entry in catalog:
            identifier = validate_id(entry['id'])
            alias = entry.get('alias', '').strip()
            namespace = entry.get('namespace', '')
            if not alias or len(alias) > 120 or alias in names or identifier in ids:
                raise ValueError('连接别名必须唯一且非空，请修改重复别名。')
            if not re.fullmatch(r'workflow_\d+', namespace):
                raise ValueError('Invalid namespace')
            names.add(alias)
            ids.add(identifier)
            entries.append({'id': identifier, 'alias': alias, 'namespace': namespace})
    with export_lock() as directory:
        catalog_path = directory / 'catalog.json'
        if catalog is not None:
            atomic_json(catalog_path, entries)
        elif catalog_path.exists():
            entries = json.loads(catalog_path.read_text(encoding='utf-8'))
        else:
            entries = []
        commands = {}
        for entry in entries:
            state = read_state(state_path(entry['id']))
            if (state.get('status') == 'connected' and state.get('verified_at')
                    and state.get('namespace') == entry['namespace']
                    and not (ROOT / (entry['id'] + '.stop')).exists()):
                port = state.get('port')
                if isinstance(port, int) and 0 < port < 65536:
                    commands[entry['alias']] = f'ssh -p {port} 127.0.0.1'
        path = directory / 'connections.json'
        atomic_json(path, commands)
    return str(path)

def profile_data(value):
    """Whitelist non-secret profile fields; never persist tokens or arbitrary input."""
    if not isinstance(value, dict):
        raise ValueError('Invalid profile')
    users, connections = [], []
    for user in value.get('users', []):
        name = user.get('name', '')
        if not re.fullmatch(r'[a-zA-Z0-9._@-]{1,100}', name):
            raise ValueError('Invalid login name')
        item = {'id': validate_id(user['id']), 'name': name}
        auth = user.get('auth')
        if isinstance(auth, dict) and isinstance(auth.get('status'), str):
            item['auth'] = {'status': auth['status'][:100], 'updatedAt': auth.get('updatedAt')}
        users.append(item)
    for connection in value.get('connections', []):
        namespace = connection.get('namespace', '')
        alias = connection.get('alias', '').strip()
        if not re.fullmatch(r'workflow_\d+', namespace) or not alias or len(alias) > 120:
            raise ValueError('Invalid connection')
        connections.append({'id': validate_id(connection['id']), 'alias': alias,
                            'namespace': namespace, 'createdAt': connection.get('createdAt')})
    if len({c['alias'] for c in connections}) != len(connections):
        raise ValueError('Duplicate connection alias')
    selected = value.get('selected')
    return {'schemaVersion': 2, 'users': users, 'connections': connections,
            'selected': selected if selected in {u['id'] for u in users} else (users[0]['id'] if users else None)}

def settings():
    try:
        value = json.loads((ROOT / 'settings.json').read_text())['interval_minutes']
        return {'interval_minutes': validate_interval(value)}
    except (OSError, ValueError, KeyError, TypeError):
        return {'interval_minutes': 5}

def validate_interval(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= value <= 1440:
        raise ValueError('检测间隔须为 0.1 至 1440 分钟')
    return value

def reset_countdown(state, interval):
    state.update(countdown_started_at=time.time(), interval_seconds=interval)
    state['next_check_at'] = state['countdown_started_at'] + interval

def close_tunnel(process):
    if process and process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
    if process and process.stdin:
        process.stdin.close()

def monitor(identifier, namespace, login, stop, state):
    process = None
    check = ROOT / (identifier + '.check')
    retry_at = 0
    last_probe = 0
    watch_due = 0
    try:
        while not stop.exists():
            interval = settings()['interval_minutes'] * 60
            watching = (ROOT / (identifier + '.watch')).exists()
            if watching != state.get('gpu_watching', False):
                state['gpu_watching'] = watching
                watch_due = 0
                state['gpu_next_check_at'] = time.time() if watching else None
                write_state(identifier, state)
            forced = check.exists()
            if forced:
                check.unlink(missing_ok=True)
                last_probe = time.monotonic()
                reset_countdown(state, interval)
                write_state(identifier, state)
            if process is None:
                if time.monotonic() < retry_at and not forced:
                    time.sleep(0.2)
                    continue
                state.update(status='reconnecting' if state.get('port_refreshed_at') else 'connecting')
                reset_countdown(state, interval)
                state.pop('ssh_command', None)
                write_state(identifier, state)
                try:
                    process = start_tunnel_process(namespace, login)
                except OSError as exc:
                    state.update(status='reconnecting', error=clean(str(exc)))
                    write_state(identifier, state)
                    retry_at = time.monotonic() + interval
                    continue
                chunks = queue.Queue()
                def reader(proc=process, sink=chunks):
                    try:
                        while True:
                            chunk = proc.stdout.read1(4096)
                            if not chunk:
                                break
                            sink.put(chunk)
                    except (OSError, ValueError):
                        pass
                threading.Thread(target=reader, daemon=True).start()
                output = b''
                started = time.monotonic()
                verified = False
                port = None
            while not chunks.empty():
                output = (output + chunks.get())[-16384:]
            text = output.decode('utf-8', errors='replace')
            worker_ips = re.findall(r'https?://([0-9.]+):\d+/v1/proxy\b', text)
            if worker_ips and sorted(set(worker_ips)) != state.get('worker_ips'):
                state.update(worker_ips=sorted(set(worker_ips)), worker_observed_at=time.time())
                write_state(identifier, state)
            failure = None
            if process.poll() is not None:
                failure = clean(text) or 'ssctl 进程已退出'
            elif port is None:
                match = re.search(r'ssh\s+-p\s+(\d+)\s+127\.0\.0\.1', text)
                if match:
                    port = int(match[1])
                    state.update(status='checking')
                    write_state(identifier, state)
                elif time.monotonic() - started > 90:
                    failure = clean(text) or '等待隧道超过 90 秒'
            if not failure and port and (not verified or forced or time.monotonic() - last_probe >= interval):
                last_probe = time.monotonic()
                reset_countdown(state, interval)
                state['probe_running'] = True
                write_state(identifier, state)
                good, detail = probe_ssh(port)
                watch_due = last_probe + 2
                state['gpu_next_check_at'] = time.time() + max(0, watch_due - time.monotonic()) if watching else None
                state['probe_running'] = False
                if stop.exists():
                    break
                if good:
                    if not verified:
                        state['port_refreshed_at'] = time.time()
                    verified = True
                    scan = detail if isinstance(detail, dict) else {'hostname': detail}
                    state.update(status='connected', port=port, ssh_command=f'ssh -p {port} 127.0.0.1', verified_at=time.time(), hostname=scan['hostname'])
                    state['gpu'] = scan.get('gpu', {'error': 'GPU scan unavailable', 'cards': []})
                    state['gpu']['updated_at'] = time.time()
                    state.pop('error', None)
                    write_state(identifier, state)
                else:
                    failure = detail
            elif not failure and port and verified and watching and time.monotonic() >= watch_due:
                scan_started = time.monotonic()
                state['gpu_scan_running'] = True
                state['gpu_next_check_at'] = None
                write_state(identifier, state)
                good, detail = probe_ssh(port)
                state['gpu_scan_running'] = False
                # Do not start overlapping SSH requests if the remote scan is slow.
                watch_due = scan_started + 2
                state['gpu_next_check_at'] = time.time() + max(0, watch_due - time.monotonic())
                if stop.exists():
                    break
                state['gpu'] = (detail.get('gpu', {'cards': [], 'error': '显卡扫描不可用'})
                                if good and isinstance(detail, dict) else {'cards': [], 'error': clean(str(detail))})
                state['gpu']['updated_at'] = time.time()
                write_state(identifier, state)
            if failure:
                state.update(status='reconnecting', error=failure)
                state.pop('ssh_command', None)
                state.pop('verified_at', None)
                write_state(identifier, state)
                close_tunnel(process)
                process = None
                # A previously healthy tunnel gets one immediate rebuild.
                # Failed rebuilds wait the configured interval, preventing a loop.
                retry_at = time.monotonic() + (0 if verified else interval)
                if not verified:
                    reset_countdown(state, interval)
                    write_state(identifier, state)
            time.sleep(0.2)
    finally:
        close_tunnel(process)
        check.unlink(missing_ok=True)
        (ROOT / (identifier + '.watch')).unlink(missing_ok=True)
        state.update(gpu_watching=False, gpu_scan_running=False, gpu_next_check_at=None)

GPU_MARKER = '__AIS_GPU_SCAN__'
SSH_SCAN = "hostname && printf '\\n__AIS_GPU_SCAN__\\n'; if command -v timeout >/dev/null 2>&1; then timeout 5s nvidia-smi -q -x 2>/dev/null; fi; exit 0"

def parse_gpu(output):
    try:
        root = ET.fromstring(output.strip())
        cards = []
        for gpu in root.findall('gpu'):
            def number(path):
                value = gpu.findtext(path, '')
                match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:MiB|%)?\s*', value)
                return float(match[1]) if match else None
            utilization = number('utilization/gpu_util')
            processes = gpu.find('processes')
            processes_known = processes is not None and (processes.text or '').strip() in ('', 'None')
            count = len(processes.findall('process_info')) if processes is not None else 0
            used = number('fb_memory_usage/used')
            if utilization is not None and utilization > 0:
                status = 'busy'
            elif not processes_known:
                status = 'unknown'
            elif count == 0:
                status = 'idle'
            elif utilization == 0 and used is not None and used > 0:
                status = 'spinning'
            else:
                status = 'unknown'
            cards.append({'index': len(cards), 'name': gpu.findtext('product_name', 'Unknown GPU'),
                          'memory_used': used, 'memory_total': number('fb_memory_usage/total'),
                          'utilization': utilization, 'status': status})
        return {'cards': cards} if cards else {'cards': [], 'error': '未检测到可见 GPU'}
    except (ET.ParseError, ValueError):
        return {'cards': [], 'error': '显卡扫描不可用：nvidia-smi 缺失、超时或返回格式异常'}

def ssh_diagnostic(stderr, timed_out=False):
    if isinstance(stderr, bytes):
        stderr = stderr.decode('utf-8', errors='replace')
    stderr = stderr or ''
    if 'Authenticated to ' in stderr:
        stage = '远端命令执行'
    elif 'Remote protocol version' in stderr:
        stage = 'SSH 密钥交换或认证'
    elif 'Connection established' in stderr:
        stage = 'SSH 握手（本地 TCP 已连接）'
    else:
        stage = 'SSH 连接建立'
    # Keep only bounded, sanitized diagnostics, never raw stdout.
    tail = clean('\n'.join(stderr.splitlines()[-6:]))[-1200:]
    return stage + ('超时' if timed_out else '失败') + ('：' + tail if tail else '')


def ssh_run(port, command, timeout=16):
    return subprocess.run([shutil.which('ssh.exe') or 'ssh', '-v', '-p', str(port),
        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6',
        '-o', 'ConnectionAttempts=1', '-o', 'StrictHostKeyChecking=accept-new',
        '127.0.0.1', command], stdin=subprocess.DEVNULL, capture_output=True,
        encoding='utf-8', errors='replace', timeout=timeout, creationflags=NO_WINDOW)


def scan_gpu(port):
    try:
        result = ssh_run(port, "if command -v timeout >/dev/null 2>&1; then timeout 5s nvidia-smi -q -x; else nvidia-smi -q -x; fi")
        if result.returncode:
            return {'cards': [], 'error': 'GPU 扫描：' + ssh_diagnostic(result.stderr)}
        return parse_gpu(result.stdout)
    except subprocess.TimeoutExpired as exc:
        return {'cards': [], 'error': 'GPU 扫描：' + ssh_diagnostic(exc.stderr, True)}
    except OSError as exc:
        return {'cards': [], 'error': 'GPU 扫描：' + clean(str(exc))}


def probe_ssh(port):
    try:
        result = ssh_run(port, 'hostname')
        if result.returncode:
            return False, ssh_diagnostic(result.stderr)
        hostname = result.stdout.strip()
        if not hostname:
            return False, '远端 hostname 命令未返回主机名'
    except subprocess.TimeoutExpired as exc:
        return False, ssh_diagnostic(exc.stderr, True)
    except OSError as exc:
        return False, '本地 SSH 启动失败：' + clean(str(exc))
    # GPU failures must never invalidate a successful SSH health check.
    return True, {'hostname': hostname, 'gpu': scan_gpu(port)}

def environment(login):
    env = os.environ.copy()
    for key in ('SEASTAR_TOKEN', 'SEASTAR_TOKEN_NAME', 'SEASTAR_KEYRING_TYPE'):
        env.pop(key, None)
    env['PATH'] = str(SSCTL.parent) + os.pathsep + env.get('PATH', '')
    env['SEASTAR_TOKEN_NAME'] = 'ais-connector-' + hashlib.sha256(login.encode()).hexdigest()[:24]
    env['SEASTAR_KEYRING_TYPE'] = 'wincred' if os.name == 'nt' else 'keychain'
    return env

def start_tunnel_process(namespace, login):
    # ssctl's connection lifecycle reads stdin. DEVNULL immediately supplies EOF
    # and can leave its local listener alive while SSH forwarding is unusable.
    # Keep this pipe open for the full tunnel lifetime; do not call communicate().
    return subprocess.Popen(
        [str(SSCTL), 'connect', '-service-type', 'ssh', '-ais_exp_namespace',
         namespace, '-container-name', 'main'], env=environment(login),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=NO_WINDOW, **({'start_new_session': True} if os.name != 'nt' else {}))

def clean(text, token=''):
    text = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', text)
    text = re.sub(r'\bat_[\w-]+|\beyJ[\w.-]+', '[REDACTED]', text)
    if token:
        text = text.replace(token, '[REDACTED]')
    text = re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)((?:[\w-]*token|password|secret|authorization)\s*[=:]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?<![\w])\d{6}(?![\w])', '[REDACTED]', text)
    return text[-1600:]

def validate_id(value):
    return str(uuid.UUID(value))

def state_path(identifier):
    return ROOT / (validate_id(identifier) + '.json')

def write_state(identifier, data):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = state_path(identifier)
    data['updated_at'] = time.time()
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)
    log_event('connection.state', 'error' if data.get('error') else 'info', id=identifier,
              **{k: data.get(k) for k in ('namespace', 'loginName', 'status', 'port', 'probe_running', 'error')})
    # Export failure must not tear down an otherwise healthy SSH tunnel.
    try:
        publish_agent_connections()
    except (OSError, ValueError) as exc:
        log_event('agent.export_failed', 'error', id=identifier, error=str(exc))

def alive(pid):
    if not pid:
        return False
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)

def worker_running(path, data):
    """A PID can be reused. A live supervisor must also hold its connection lock."""
    if not alive(data.get('pid')):
        return False
    try:
        with path.with_suffix('.lock').open('r+b') as lock:
            if os.name == 'nt':
                import msvcrt
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    import errno
                    if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        return True
                    raise
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except OSError:
        return False
    return False

def read_state(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        data.setdefault('updated_at', path.stat().st_mtime)
        if data['status'] in ACTIVE and not worker_running(path, data):
            data.update(status='error', error='后台进程已退出，请重新初始化连接。')
            data.pop('ssh_command', None)
            data.pop('verified_at', None)
        elif data['status'] == 'connected' and not data.get('verified_at'):
            data.update(status='degraded', error='旧版连接未验证 SSH，请断开后重新初始化。')
        return data
    except (OSError, ValueError, KeyError):
        return {'status': 'stopped'}

def worker(identifier, namespace, login):
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = (ROOT / (identifier + '.lock')).open('a+b')
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return
    stop = ROOT / (identifier + '.stop')
    stop.unlink(missing_ok=True)
    (ROOT / (identifier + '.watch')).unlink(missing_ok=True)
    state = {'pid': os.getpid(), 'status': 'connecting', 'namespace': namespace, 'loginName': login, 'monitor_version': 3}
    write_state(identifier, state)
    process = None
    try:
        config = Path.home() / '.ssctl' / 'ssh_config'
        config.parent.mkdir(parents=True, exist_ok=True)
        if not config.exists():
            config.touch()
        monitor(identifier, namespace, login, stop, state)
        state.update(status='stopped')
    except Exception as exc:
        state.update(status='error', error=clean(str(exc)))
    finally:
        state.pop('ssh_command', None)
        write_state(identifier, state)
        stop.unlink(missing_ok=True)
        lock.close()

def dispatch(request):
    action = request.get('action')
    tracked = action in {'login', 'connect', 'stop', 'check', 'settings', 'profile_save', 'profile_init', 'sync_connections'}
    fields = {k: request.get(k) for k in ('id', 'namespace', 'loginName')}
    if tracked:
        log_event('operation.started', action=action, **fields)
    try:
        result = dispatch_request(request)
    except Exception as exc:
        if action != 'logs':
            # Authentication output can contain exchanged credentials: do not log it.
            detail = 'Authentication failed; see login UI' if action == 'login' else clean(str(exc), request.get('token', ''))
            log_event('operation.failed', 'error', action=action, error=detail, **fields)
        raise
    if tracked:
        log_event('operation.completed', action=action, **fields)
    return result

def dispatch_request(request):
    action = request.get('action')
    ROOT.mkdir(parents=True, exist_ok=True)
    if action == 'gpu_watch':
        identifier = validate_id(request['id'])
        enabled = request.get('enabled')
        if not isinstance(enabled, bool):
            raise ValueError('Invalid watch setting')
        current = read_state(state_path(identifier))
        if enabled and (current.get('monitor_version', 0) < 3 or current.get('status') != 'connected'):
            raise ValueError('请先断开并重新初始化连接以加载注视功能，并等待 SSH 连接成功。')
        path = ROOT / (identifier + '.watch')
        if enabled:
            path.touch()
        else:
            path.unlink(missing_ok=True)
        log_event('gpu.watch_enabled' if enabled else 'gpu.watch_disabled', id=identifier)
        return {}
    if action == 'vpn_diagnose':
        spec = importlib.util.spec_from_file_location('ais_vpn', Path(__file__).with_name('vpn.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.diagnose(ROOT)
    if action == 'agent_info':
        return {'agent_file': str(ROOT / 'agent' / 'connections.json'),
                'skill_file': str(Path(__file__).resolve().parents[1] / 'skills' / 'ais-connector' / 'SKILL.md')}
    if action == 'logs':
        log_snapshots()
        return {'entries': read_logs(), 'log_file': str(ROOT / 'logs' / 'events.sqlite3')}
    if action in ('profile_get', 'profile_save', 'profile_init'):
        path = ROOT / 'profile.json'
        with export_lock():
            if action == 'profile_save' or (action == 'profile_init' and not path.exists()):
                atomic_json(path, profile_data(request['profile']))
            profile = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        return {'profile': profile, 'personal_directory': str(ROOT)}
    if action == 'status':
        agent_path = publish_agent_connections()
        return {'connections': {p.stem: read_state(p) for p in ROOT.glob('*.json') if p.name != 'settings.json'}, 'ssctlInstalled': SSCTL.exists(), 'settings': settings(), 'agent_file': agent_path}
    if action == 'sync_connections':
        return {'agent_file': publish_agent_connections(request.get('connections'))}
    if action == 'settings':
        value = validate_interval(request.get('interval_minutes'))
        temp = ROOT / ('settings-' + uuid.uuid4().hex + '.tmp')
        temp.write_text(json.dumps({'interval_minutes': value}))
        os.replace(temp, ROOT / 'settings.json')
        for path in ROOT.glob('*.json'):
            if path.name != 'settings.json' and read_state(path).get('status') in ACTIVE:
                (ROOT / (validate_id(path.stem) + '.check')).touch()
        return {'settings': settings()}
    if action == 'check':
        identifier = validate_id(request['id'])
        current = read_state(state_path(identifier))
        if current.get('status') not in ACTIVE:
            raise ValueError('连接未运行，请先初始化连接。')
        if current.get('monitor_version') not in (2, 3):
            raise ValueError('此连接由旧版后台维护，请断开后重新初始化以启用定时检测。')
        (ROOT / (identifier + '.check')).touch()
        return {}
    if action == 'stop':
        identifier = validate_id(request['id'])
        (ROOT / (identifier + '.stop')).touch()
        publish_agent_connections()
        return {}
    if action not in ('login', 'connect'):
        raise ValueError('Unsupported action')
    if not SSCTL.is_file():
        raise ValueError('未找到 ssctl.exe：' + str(SSCTL))
    login = request.get('loginName', '')
    if not re.fullmatch(r'[a-zA-Z0-9._@-]{1,100}', login):
        raise ValueError('Invalid login name')
    if action == 'login':
        token = request.get('token', '')
        if not re.fullmatch(r'\d{6}', token):
            raise ValueError('请输入六位 Token')
        try:
            # ssctl v1.16.13's stdin flag prompts through a terminal reader even
            # when stdin is a pipe. Use its explicit noninteractive token flag.
            # No shell is involved; never log this argument list.
            result = subprocess.run([str(SSCTL), 'login', '-login-name', login, '-alilang-token', token], stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8', errors='replace', timeout=45, env=environment(login), creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise ValueError('认证超时，请检查网络后使用新的 Token 重试。') from None
        if result.returncode:
            raise ValueError(clean(result.stderr or result.stdout, token) or '认证失败')
        return {}
    identifier = validate_id(request['id'])
    namespace = request.get('namespace', '')
    if not re.fullmatch(r'workflow_\d+', namespace):
        raise ValueError('Invalid namespace')
    current = read_state(state_path(identifier))
    if current.get('status') in ACTIVE:
        if current.get('namespace') != namespace or current.get('loginName') != login:
            raise ValueError('连接标识已被其他目标使用')
        return current
    python = Path(sys.executable).with_name('pythonw.exe')
    if not python.exists():
        python = Path(sys.executable)
    subprocess.Popen([str(python), str(Path(__file__).resolve()), '--worker', identifier, namespace, login], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW | getattr(subprocess, 'DETACHED_PROCESS', 0), close_fds=True, **({'start_new_session': True} if os.name != 'nt' else {}))
    for _ in range(30):
        current = read_state(state_path(identifier))
        if current.get('status') in ACTIVE:
            return current
        time.sleep(0.1)
    raise ValueError('后台进程启动失败，请检查 Python 安装。')

def read_exact(stream, size):
    result = b''
    while len(result) < size:
        chunk = stream.read(size - len(result))
        if not chunk:
            raise EOFError()
        result += chunk
    return result

def main():
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    while True:
        try:
            length = struct.unpack('<I', read_exact(sys.stdin.buffer, 4))[0]
            if length > 65536:
                return
            request = json.loads(read_exact(sys.stdin.buffer, length))
        except (EOFError, ValueError):
            return
        try:
            result = {'ok': True, **dispatch(request)}
        except Exception as exc:
            result = {'ok': False, 'error': clean(str(exc), request.get('token', ''))}
        payload = json.dumps(result, ensure_ascii=False).encode('utf-8')
        sys.stdout.buffer.write(struct.pack('<I', len(payload)) + payload)
        sys.stdout.buffer.flush()

if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--worker':
        worker(*sys.argv[2:])
    else:
        main()
