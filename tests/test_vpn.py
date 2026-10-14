import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('vpn',Path(__file__).resolve().parents[1]/'native-host/vpn.py')
vpn=importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpn)

class VPNTests(unittest.TestCase):
    def test_worker_urls_ignore_unrelated_and_invalid_ips(self):
        self.assertEqual(vpn.worker_urls('https://203.0.113.8:9312/v1/proxy local 192.168.1.2 https://999.1.2.3:9312/v1/proxy'),['203.0.113.8'])

    def test_specific_route_wins_and_vpn_gateway_is_dynamic(self):
        routes=[{'InterfaceIndex':2,'NextHop':'192.168.1.1','DestinationPrefix':'0.0.0.0/0','RouteMetric':1},
                {'InterfaceIndex':12,'NextHop':'10.2.0.1','DestinationPrefix':'203.0.113.8/32','RouteMetric':50}]
        network={'routes':routes,'adapters':[{'ifIndex':12,'Name':'Office','InterfaceDescription':'TAP-Windows'}]}
        state={'pid':5,'namespace':'workflow_1','error':'https://203.0.113.8:9312/v1/proxy failed'}
        result=vpn.analyze(network,{'c':state},[{'id':'c','alias':'Example'}])
        self.assertEqual(result['targets'][0]['route']['InterfaceIndex'],12)
        self.assertEqual(result['candidates'][0]['gateway'],'10.2.0.1')
        self.assertTrue(result['candidates'][0]['likely_vpn'])

    def test_only_owned_ssctl_endpoints_and_no_gateway_guess(self):
        network={'routes':[], 'adapters':[{'ifIndex':9,'Name':'VPN','InterfaceDescription':'TUN'}],
                 'processes':[{'ProcessId':11,'ParentProcessId':10,'Name':'ssctl.exe'}],
                 'sockets':[{'OwningProcess':11,'RemoteAddress':'203.0.113.9','RemotePort':9999},
                            {'OwningProcess':22,'RemoteAddress':'203.0.113.10','RemotePort':9999}]}
        result=vpn.analyze(network,{'c':{'pid':10}},[])
        self.assertEqual([t['ip'] for t in result['targets']],['203.0.113.9'])
        self.assertEqual(result['candidates'],[])
