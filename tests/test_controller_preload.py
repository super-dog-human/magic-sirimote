import io
import json
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/integrated'))
from controller_preload import token, await_start, revalidate


class ControllerPreloadTests(unittest.TestCase):
    def test_only_the_exact_single_release_starts(self):
        value='a'*32
        for raw,expected in [('',False),(json.dumps({'action':'start','token':value})+'\n',True)]:
            sink=io.StringIO()
            self.assertEqual(await_start(value,source=io.StringIO(raw),sink=sink,pid=12,ticks=34),expected)
            self.assertEqual(json.loads(sink.getvalue()),{'stage':'controller-preloaded','token':value,'pid':12,'startTicks':34})
        for raw in ('{}\n','{"action":"start","token":"wrong"}\n','x'*256,
                    json.dumps({'action':'start','token':value})+'\n{}\n',
                    '{"action":"start","action":"start","token":"'+value+'"}\n'):
            with self.assertRaises((RuntimeError,ValueError)):
                await_start(value,source=io.StringIO(raw),sink=io.StringIO(),pid=12,ticks=34)

    def test_missing_marker_keeps_ordinary_start_and_invalid_marker_fails(self):
        self.assertIsNone(token({}))
        self.assertEqual(token({'MAGIC_SIRIMOTE_PRELOAD':'a'*32}),'a'*32)
        with self.assertRaises(RuntimeError):token({'MAGIC_SIRIMOTE_PRELOAD':'anything'})

    def test_fresh_settings_code_process_and_conflict_checks_are_required(self):
        values={'remote':'original'};pins={'controller':{'pin':1},'receiver':{'pin':2}}
        def arguments():
            return dict(load_values=lambda:dict(values),read_pin=lambda role:dict(pins[role]),
                        verify_package=lambda role,pin:True,verify_process=lambda:True,check_conflicts=lambda:None)
        revalidate(values,pins,**arguments())
        for change in ({'load_values':lambda:{'remote':'changed'}}, {'read_pin':lambda role:{}},
                       {'verify_package':lambda role,pin:False},{'verify_process':lambda:False},
                       {'check_conflicts':Mock(side_effect=RuntimeError('live receiver'))}):
            with self.assertRaises(RuntimeError):revalidate(values,pins,**{**arguments(),**change})
