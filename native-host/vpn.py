"""Read-only Windows route discovery; generated commands are never executed here."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time

NETWORK_QUERY = r'''
$ErrorActionPreference = 'Stop'
$adapters = @(Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object ifIndex,Name,InterfaceDescription)
$routes = @(Get-NetRoute -AddressFamily IPv4 -PolicyStore ActiveStore | Select-Object InterfaceIndex,DestinationPrefix,NextHop,RouteMetric,InterfaceMetric)
$processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name)
$sockets = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $_.RemotePort -gt 0 } | Select-Object OwningProcess,RemoteAddress,RemotePort,State)
@{adapters=$adapters;routes=$routes;processes=$processes;sockets=$sockets} | ConvertTo-Json -Depth 5 -Compress
'''

def ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
            return None
        return str(address)
    except (ValueError, TypeError):
        return None

def worker_urls(text):
    # Only an explicit worker proxy URL is evidence, not arbitrary IPs in logs.
    return sorted({ip for raw in re.findall(r'https?://([0-9.]+):\d+/v1/proxy\b', text or '') if (ip := ipv4(raw))})

def best_route(target, routes):
    matches = []
    for route in routes:
        try:
            network = ipaddress.IPv4Network(route['DestinationPrefix'])
            if ipaddress.IPv4Address(target) in network:
                matches.append((network.prefixlen, -(int(route.get('RouteMetric', 0)) + int(route.get('InterfaceMetric') or 0)), route))
        except (ValueError, KeyError, TypeError):
            continue
    return max(matches, key=lambda item: item[:2])[2] if matches else None

def analyze(network, states, catalog):
    routes = network.get('routes', [])
    aliases = {c['id']: c.get('alias', c['id']) for c in catalog}
    targets = []
    for identifier, state in states.items():
        evidence = {ip: '最近错误中的 worker URL（可能已过期）' for ip in worker_urls(state.get('error', ''))}
        for ip in state.get('worker_ips', []):
            if ipv4(ip):
                evidence[ip] = '后台 ssctl 输出（请核对更新时间）'
        descendants = {state.get('pid')}
        for _ in range(8):
            descendants.update(p['ProcessId'] for p in network.get('processes', []) if p.get('ParentProcessId') in descendants)
        ssctl = {p['ProcessId'] for p in network.get('processes', []) if p.get('ProcessId') in descendants and p.get('Name', '').lower() in ('ssctl.exe', 'ssctl')}
        for socket in network.get('sockets', []):
            address = ipv4(socket.get('RemoteAddress'))
            # Port alone does not prove a worker identity. Surface it as a candidate.
            if socket.get('OwningProcess') in ssctl and address and int(socket.get('RemotePort', 0)) not in (80, 443, 53):
                evidence[address] = 'ssctl 网络端点候选（需确认是 worker）'
        for address, source in evidence.items():
            targets.append({'id': identifier, 'alias': aliases.get(identifier, state.get('namespace', identifier)),
                            'ip': address, 'source': source, 'updated_at': state.get('worker_observed_at', state.get('updated_at')),
                            'route': best_route(address, routes)})
    candidates = []
    for adapter in network.get('adapters', []):
        index = int(adapter['ifIndex'])
        gateways = sorted({ip for r in routes if int(r['InterfaceIndex']) == index and (ip := ipv4(r.get('NextHop')))})
        name = adapter.get('Name', '')
        description = adapter.get('InterfaceDescription', '')
        likely = bool(re.search(r'vpn|tap|tun|wireguard|anyconnect|fortinet|globalprotect|pangp|alilang', name+' '+description, re.I))
        for gateway in gateways:
            candidates.append({'index': index, 'name': name, 'description': description, 'gateway': gateway, 'likely_vpn': likely})
    return {'targets': targets, 'candidates': candidates, 'detected_at': time.time()}

def diagnose(root):
    if os.name != 'nt':
        raise ValueError('居家路由诊断目前仅支持 Windows；不会在 macOS 生成 Windows 命令。')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', NETWORK_QUERY],
                            capture_output=True, timeout=25, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Windows 网络信息读取失败，请确认 NetTCPIP 模块可用。')
    # Windows PowerShell redirects output using the local ANSI code page.
    # Avoid setting Console.OutputEncoding: managed desktops may prohibit it.
    network = json.loads(result.stdout.decode('mbcs'))
    states = {}
    for path in root.glob('*.json'):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if state.get('namespace'):
                states[path.stem] = state
        except (OSError, ValueError):
            continue
    catalog_path = root / 'agent/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else []
    return analyze(network, states, catalog)
