"""Interrupted-reset reconnection; no TV or firmware writes in these tests."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/native')]
spec=importlib.util.spec_from_file_location('pairing_flow',ROOT/'src/pairing/flow.py')
m=importlib.util.module_from_spec(spec);sys.modules['pairing_flow']=m;spec.loader.exec_module(m)
from reset_recovery import ResetRecovery
import settings, reset_remote
from test_pairing_flow import Bus, AD, DIS, uuid
REMOTE='aa:bb:cc:dd:ee:10'; TV='aa:bb:cc:dd:ee:20'
VALUES={'schema':1,'remoteAddress':REMOTE,'adapterAddress':TV,'remoteName':'TESTREMOTE','gyroEnabled':True,'gyroSensitivity':3}

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name);settings.save(self.state,VALUES)
        self.value=reset_remote.create(self.state);self.bus=Bus()
        self.flow=ResetRecovery(self.bus,self.state,self.value)
    def reply(self,tag,**values):
        self.bus.incoming.append((tag,{'returnValue':True,**values}));self.flow.tick()
    def devices(self,paired=True,**extra):
        return {'devices':[{'address':REMOTE,'paired':paired,**extra},
                           {'address':'aa:bb:cc:dd:ee:99','paired':True}]}
    def inspect(self,paired=True):
        self.reply('adapter',adapters=[{'adapterAddress':TV,'powered':True}])
        self.reply('devices',**self.devices(paired))
    def begin_repair(self):
        self.inspect()
        self.reply('identity-client',returnValue=False,errorText='Connection failed')
        self.assertEqual(self.flow.phase,'repair-preflight')
        self.reply('repair-idle',cleanStop=True,processes={'legacy':[]},startup={'enabled':False})
        self.reply('repair-adapter',adapters=[{'adapterAddress':TV,'powered':True}])
    def test_stale_saved_bond_repaired_then_same_remote_scanned(self):
        self.begin_repair()
        self.reply('repair-fresh',**self.devices())
        durable=reset_remote.load(self.state)
        self.assertEqual(durable['phase'],'reconnecting')
        self.assertEqual(durable['completed'],[]);self.assertFalse(durable['unpaired'])
        self.assertEqual(self.bus.sent[-1][1:],('adapter/unpair',{'address':REMOTE}))
        self.reply('repair-unpair');self.reply('repair-check',**self.devices(False,adapterAddress=''))
        self.assertEqual(self.flow.phase,'scanning');self.assertIn('MENU',self.flow.message)
        self.reply('scan',device={'address':'aa:bb:cc:dd:ee:99','scanRecord':AD})
        self.assertEqual(self.flow.phase,'scanning')
        self.reply('scan',device={'address':REMOTE,'scanRecord':AD})
        self.assertEqual(self.flow.phase,'pair-preflight')
        self.reply('pair-idle',cleanStop=True,startup={'enabled':False})
        self.reply('pair-fresh',**self.devices(False))
        self.reply('pair',request='endPairing',address=REMOTE)
        self.reply('paired-check',**self.devices())
        self.identity()
        self.reply('hid-check',address=REMOTE,adapterAddress=TV,connected=True,connecting=False)
        self.reply('initialize')
        self.assertEqual(self.flow.phase,'success');self.assertEqual(self.flow.serial,'TESTREMOTE')
        self.assertEqual(settings.load(self.state),VALUES)
        writes=[params for _,method,params in self.bus.sent if method=='hid/internal/setReport']
        self.assertEqual(writes,[{'address':REMOTE,'reportType':'feature','reportData':[240,175]}])
    def identity(self,serial='TESTREMOTE'):
        self.reply('identity-client',address=REMOTE,adapterAddress=TV,clientId='1')
        self.reply('identity-services')
        self.reply('identity-inventory',address=REMOTE,adapterAddress=TV,services=[
            {'service':DIS,'characteristics':[{'characteristic':uuid(c)} for c in ('2a50','2a25','2a26')]}])
        self.reply('identity-product',address=REMOTE,adapterAddress=TV,service=DIS,
            values=[{'characteristic':uuid('2a50'),'value':{'bytes':[1,76,0,102,2,0,0]}}])
        self.reply('identity-serial',address=REMOTE,adapterAddress=TV,service=DIS,
            values=[{'characteristic':uuid('2a25'),'value':{'bytes':list(serial.encode())}}])
        if serial=='TESTREMOTE':
            self.reply('identity-firmware',address=REMOTE,adapterAddress=TV,service=DIS,
                values=[{'characteristic':uuid('2a26'),'value':{'bytes':list(b'0257')}}])
    def test_working_bond_is_retained_until_ir_stage(self):
        self.inspect();self.identity()
        self.reply('hid-check',address=REMOTE,adapterAddress=TV,connected=True,connecting=False)
        self.reply('initialize');self.assertEqual(self.flow.phase,'success')
        self.assertFalse(any(method=='adapter/unpair' for _,method,_ in self.bus.sent))
    def test_lost_unpair_reply_retains_journal_and_reopen_queries_before_scanning(self):
        self.begin_repair();self.reply('repair-fresh',**self.devices())
        self.reply('repair-unpair',returnValue=False,errorText='timed out')
        self.assertEqual(self.flow.phase,'failed')
        self.assertEqual(sum(method=='adapter/unpair' for _,method,_ in self.bus.sent),1)
        self.bus=Bus();self.flow=ResetRecovery(self.bus,self.state,reset_remote.load(self.state))
        self.inspect(False);self.assertEqual(self.flow.phase,'scanning')
        self.assertFalse(any(method=='adapter/unpair' for _,method,_ in self.bus.sent))
    def test_wrong_serial_never_sends_input_or_ir(self):
        self.inspect();self.identity('OTHERREMOTE')
        self.assertEqual(self.flow.phase,'failed')
        self.assertFalse(any(method in ('adapter/unpair','hid/internal/setReport') for _,method,_ in self.bus.sent))
    def test_successful_connect_reply_but_disconnected_status_can_repair(self):
        self.inspect();self.identity()
        self.reply('hid-check',address=REMOTE,adapterAddress=TV,connected=False,connecting=False)
        self.reply('connect',address=REMOTE,adapterAddress=TV)
        self.reply('connected-check',address=REMOTE,adapterAddress=TV,connected=False,connecting=False)
        self.assertEqual(self.flow.phase,'repair-preflight')
        self.assertFalse(self.flow.input_sent)

    def test_error_for_another_peer_does_not_start_repair(self):
        self.inspect()
        self.reply('identity-client',returnValue=False,address='aa:bb:cc:dd:ee:99')
        self.assertEqual(self.flow.phase,'failed');self.assertFalse(self.flow.repair_started)

    def test_changed_adapter_never_discards_bond(self):
        self.reply('adapter',adapters=[{'adapterAddress':'aa:bb:cc:dd:ee:99','powered':True}])
        self.assertEqual(self.flow.phase,'failed')
        self.assertFalse(any(method=='adapter/unpair' for _,method,_ in self.bus.sent))
    def test_active_input_blocks_repair(self):
        self.inspect();self.reply('identity-client',returnValue=False)
        self.reply('repair-idle',cleanStop=False,startup={'enabled':False})
        self.assertEqual(self.flow.phase,'failed')
        self.assertFalse(any(method=='adapter/unpair' for _,method,_ in self.bus.sent))
    def test_changed_settings_preserved(self):
        settings.save(self.state,{**VALUES,'remoteName':'CHANGED'})
        self.inspect();self.assertEqual(self.flow.phase,'failed')
        self.assertFalse(any(method in ('adapter/unpair','hid/internal/setReport') for _,method,_ in self.bus.sent))
    def test_ambiguous_or_wrong_adapter_bond_blocks_repair(self):
        for row in ({'adapterAddress':'aa:bb:cc:dd:ee:99'},{'pairing':True},{'blocked':True}):
            with self.subTest(row=row):
                self.setUp();self.begin_repair();self.reply('repair-fresh',**self.devices(**row))
                self.assertEqual(self.flow.phase,'failed')
                self.assertFalse(any(method=='adapter/unpair' for _,method,_ in self.bus.sent))

if __name__=='__main__':unittest.main()
