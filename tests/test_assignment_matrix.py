"""Assignments must change the chosen slot only, across UI, storage and input."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src/native'),str(ROOT/'src/integrated'),str(ROOT/'src/runtime')]
import tv_assignments as table
import system_buttons as buttons
from ir_screen import InfraredScreen, CHOICES, CUSTOM
from native_manager import RuntimeSetup
from native_bus import NativeBus
from test_settings_render import DiscardingCanvas

class AssignmentMatrixTests(unittest.TestCase):
    def test_fresh_install_shows_twelve_none_slots_without_sending_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            app=InfraredScreen(Path(d))
            for _,button in table.ROWS:
                for delay in (0,2):self.assertEqual(app.cell_label(button,delay),'Do nothing')
            self.assertEqual(table.displayed_bindings(d,{}),{table.slot(b,t):'none' for _,b in table.ROWS for t in (0,2)})
            self.assertEqual(table.plan(d,{}),[])
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_explicit_press_preserved_with_unconfigured_hold_defaulting_to_none(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',8,0,'playpause')
            app=InfraredScreen(Path(d))
            self.assertEqual(app.cell_label(8,0),'Play / Pause')
            self.assertEqual(app.cell_label(8,2),'Do nothing')
            self.assertEqual(table.displayed_bindings(d,{})['08:00'],'playpause')
            self.assertEqual(table.displayed_bindings(d,{})['08:02'],'none')
            with patch.object(buttons,'CONFIGURED',{'08:00':'playpause'}):
                mapping,holds=buttons.configured_mappings({32:'back',1:'home',16:'screen-toggle'})
                self.assertEqual(mapping[8],'playpause')
                self.assertTrue(all(value is None for value in holds.values()))
                self.assertTrue(all(value is None for button,value in mapping.items() if button!=8))

    def test_first_save_with_siri_screen_off_removes_hold_before_press_without_unknown_error(self):
        with tempfile.TemporaryDirectory() as d:
            changes=table.changed_bindings(d,{'10:00':'screen-toggle'})
            ordered=table.plan(d,changes)
            self.assertEqual(ordered,[('10:02','none'),('10:00','screen-toggle')])
            self.assertLess(ordered.index(('10:02','none')),ordered.index(('10:00','screen-toggle')))
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            for key,action in ordered:
                button,delay=(int(x,16) for x in key.split(':'))
                self.assertEqual(table.assign(d,'assign',button,delay,action,program=program)['status'],'saved')
            self.assertEqual(table.load(d)['bindings'],changes)
            self.assertEqual(program.call_count,2)
            self.assertTrue(all(call.args[1]=='delete' for call in program.call_args_list))

    def test_empty_runtime_assignments_emit_no_short_or_hold_actions(self):
        with patch.object(buttons,'CONFIGURED',{}):
            mapping,holds=buttons.configured_mappings({32:'back',1:'home',16:'screen-toggle',8:'playpause'})
            actions=[];now=[0.0]
            decoder=buttons.SystemButtons(actions.append,mapping=mapping,holds=holds,clock=lambda:now[0]);decoder.bind(1)
            for _,button in table.ROWS:
                for duration in (0.1,1.0):
                    decoder.feed(1,bytes((252,0,0)));decoder.feed(1,bytes((252,0,button)))
                    now[0]+=duration;decoder.feed(1,bytes((252,0,0)))
            self.assertEqual(actions,[])

    def test_all_twelve_cells_stage_exact_button_and_press_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            drafts={}
            for row,mask in enumerate((32,1,16,8,2,4)):
                for column,delay in enumerate((0,2)):
                    app=InfraredScreen(Path(d),drafts=drafts);app.choose(row*2+column);app.choose(0)
                    self.assertEqual(drafts[table.slot(mask,delay)],'none')
            self.assertEqual(len(drafts),12)
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_none_deletes_ir_and_disables_tv_but_retains_other_slots(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',1,2,'ir:08')
            table.execute(d,'assign',32,2,'none')
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            self.assertEqual(table.assign(d,'assign',32,0,'none',program=program)['status'],'saved')
            program.assert_called_once_with(d,'delete',32,0,'')
            self.assertEqual(table.load(d)['bindings'],{'01:02':'ir:08','20:00':'none','20:02':'none'})
            with patch.object(buttons,'CONFIGURED',table.load(d)['bindings']):
                mapping,holds=buttons.configured_mappings({32:'back',1:'home'})
                actions=[];now=[0.0]
                decoder=buttons.SystemButtons(actions.append,mapping=mapping,holds=holds,clock=lambda:now[0]);decoder.bind(1)
                def feed(mask):decoder.feed(1,bytes((252,0,mask)))
                feed(0);feed(32);feed(0);self.assertEqual(actions,[])
                feed(1);now[0]=1;feed(0);self.assertEqual(actions,[]) # IR hold cannot also send Home.
                feed(1);feed(0);self.assertEqual(actions,[]) # Unknown Press has no TV fallback.

    def test_ir_choice_disables_tv_slot_and_uses_one_set_not_a_delete_then_set(self):
        with tempfile.TemporaryDirectory() as d:
            program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True})
            table.execute(d,'assign',16,0,'ir:09')
            table.assign(d,'assign',16,2,'ir:43',program=program)
            program.assert_called_once_with(d,'set',16,2,'43')
            self.assertEqual(table.load(d)['bindings'],{'10:00':'ir:09','10:02':'ir:43'})

    def test_uncertainty_and_partial_save_never_commit_or_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'assign',32,0,'ir:28')
            table.execute(d,'assign',32,2,'none')
            for status in ('not-sent','uncertain'):
                program=Mock(return_value={'status':status})
                result=table.assign(d,'assign',32,0,'none',program=program)
                self.assertEqual(result['status'],status);self.assertEqual(program.call_count,1)
                self.assertEqual(table.load(d)['bindings'],{'20:00':'ir:28','20:02':'none'})
            for result in ({'status':'submitted','connectionPreserved':False,'receiptSaved':True},
                           {'status':'submitted','connectionPreserved':True,'receiptSaved':False}):
                self.assertEqual(table.assign(d,'assign',32,0,'none',program=Mock(return_value=result))['status'],'partial')
            with patch.object(table,'execute',side_effect=OSError('full')):
                self.assertEqual(table.assign(d,'assign',32,0,'none',program=Mock(return_value={'status':'submitted','connectionPreserved':True,'receiptSaved':True}))['status'],'partial')
            self.assertEqual(table.load(d)['bindings'],{'20:00':'ir:28','20:02':'none'})

    def test_preview_assignments_are_not_silently_activated(self):
        with tempfile.TemporaryDirectory() as d:
            table.execute(d,'set',16,2)
            app=InfraredScreen(Path(d));self.assertEqual(app.tv_bindings,{})
            table.execute(d,'assign',32,0,'none')
            self.assertEqual(table.load(d),{'schema':2,'bindings':{'20:00':'none'}})

    def test_short_hold_and_none_emit_only_on_release_including_volume_bits(self):
        now=[0.0];out=[]
        dec=buttons.SystemButtons(out.append,mapping={2:'back',4:None},holds={2:'screen-toggle',4:'settings'},clock=lambda:now[0]);dec.bind(1)
        def feed(mask):dec.feed(1,bytes((252,0,mask)))
        feed(0);feed(2);now[0]=0.5;self.assertEqual(out,[]);feed(0)
        feed(2);now[0]=1.3;feed(2);self.assertEqual(out,['back']);feed(0)
        feed(4);feed(0);self.assertEqual(out,['back','screen-toggle'])
        feed(4);now[0]=2.2;feed(0);self.assertEqual(out,['back','screen-toggle','settings'])
        feed(2);dec.unbind(1);dec.bind(2);dec.feed(2,bytes((252,0,0)))
        self.assertEqual(len(out),3)

    def test_back_from_every_subscreen_returns_to_main_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            for page in ('matrix','picker','custom','review'):
                bus=Mock();app=RuntimeSetup(Path(d),bus);canvas=Mock();app.choose(6,canvas)
                if page!='matrix':app.infrared.choose(0)
                if page=='custom':app.infrared.choose(CUSTOM)
                if page=='review':app.infrared.choose(0)
                app.handle(('key',461),canvas)
                self.assertIsNone(app.infrared);self.assertFalse(app.done);bus.request.assert_not_called()
            self.assertFalse((Path(d)/table.FILE).exists())

    def test_tv_address_is_absent_from_ui_and_detected_before_disrupting_input(self):
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();app=RuntimeSetup(Path(d),bus);canvas=DiscardingCanvas();app.draw(canvas)
            self.assertNotIn('TV Bluetooth address',canvas.frames[-1]);self.assertNotIn(2,[n for n,_ in app.boxes])
            app.choose(2,canvas);self.assertIsNone(app.editing)
            app.values.update(remoteAddress='aa:bb:cc:dd:ee:10',remoteName='Remote')
            bus.tv_address.return_value='aa:bb:cc:dd:ee:20';bus.remote_name.return_value='Remote'
            values=app.detect_tv({'schema':1,**app.values})
            self.assertEqual(values['adapterAddress'],'aa:bb:cc:dd:ee:20')
            app.values['adapterAddress']='aa:bb:cc:dd:ee:22';app.choose(5,Mock());app.confirm_restart()
            bus.request.assert_not_called();self.assertIn('does not match',app.message)
            bus.tv_address.side_effect=RuntimeError('adapter unavailable');app.choose(5,Mock());app.confirm_restart()
            bus.request.assert_not_called()

    def test_adapter_query_accepts_one_valid_adapter_and_rejects_ambiguity(self):
        from settings import tv_address_from_reply
        bus=NativeBus();good={'adapterAddress':'AA:BB:CC:DD:EE:20'}
        self.assertEqual(tv_address_from_reply({'returnValue':True,'adapters':[good]}),'aa:bb:cc:dd:ee:20')
        for reply in (None,{'returnValue':False},{'returnValue':True,'adapters':[]},
                      {'returnValue':True,'adapters':[good,good]}, {'returnValue':True,'adapters':[None]},
                      {'returnValue':True,'adapters':[{'adapterAddress':'00:00:00:00:00:00'}]}):
            with self.assertRaises(RuntimeError):tv_address_from_reply(reply)
        with patch('settings.read_tv_address',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):bus.tv_address()
            self.assertFalse(bus.failed)

    def test_surface_is_not_changed_by_the_six_button_assignment_api(self):
        with tempfile.TemporaryDirectory() as d:
            program=Mock()
            with self.assertRaises(ValueError):table.assign(d,'assign',128,0,'none',program=program)
            program.assert_not_called()
            with self.assertRaises(ValueError):table.validate({'schema':2,'bindings':{'80:00':'none'}})
