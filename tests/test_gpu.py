import unittest
from test_host import host

class GPUTests(unittest.TestCase):
    def test_classification_and_details(self):
        def gpu(processes,util='0 %'):
            return f'<gpu><product_name>H200</product_name><fb_memory_usage><used>100 MiB</used><total>1000 MiB</total></fb_memory_usage><utilization><gpu_util>{util}</gpu_util></utilization>{processes}</gpu>'
        xml='<nvidia_smi_log>'+gpu('<processes/>')+gpu('<processes><process_info/></processes>')+gpu('<processes/>','40 %')+gpu('<processes>N/A</processes>')+'</nvidia_smi_log>'
        cards=host.parse_gpu(xml)['cards']
        self.assertEqual([c['status'] for c in cards],['idle','spinning','busy','unknown'])
        self.assertEqual(cards[0]['name'],'H200')
        self.assertEqual(cards[0]['memory_used'],100)

    def test_missing_or_invalid_gpu_does_not_throw(self):
        self.assertIn('error',host.parse_gpu(''))
        self.assertIn('error',host.parse_gpu('<nvidia_smi_log/>'))
