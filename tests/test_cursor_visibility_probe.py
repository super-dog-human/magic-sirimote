import unittest
from cursor_visibility_probe import observe,VisibilityClient,VisibilityState

class Tests(unittest.TestCase):
    def test_bounded_observation_preserves_unknown_until_real_event(self):
        now=[0.];rows=[]
        class Client:
            closed=False
            def poll(self,timeout):
                now[0]+=1
                return ([{'visible':False,'uptime':now[0]}] if now[0]==10 else
                        [{'visible':True,'uptime':now[0]}] if now[0] in (20,21) else [])
            def close(self):self.closed=True
        client=Client()
        observe(factory=lambda:client,clock=lambda:now[0],emit=rows.append)
        self.assertTrue(client.closed);self.assertEqual(now[0],180)
        self.assertEqual([(r['visible'],r['uptime']) for r in rows if r['event']=='visibility'],[(False,10),(True,20)])
    def test_failure_closes_only_own_client(self):
        rows=[]
        class Client:
            closed=False
            def poll(self,timeout):raise OSError('closed')
            def close(self):self.closed=True
        client=Client();observe(factory=lambda:client,emit=rows.append)
        self.assertTrue(client.closed);self.assertEqual(rows[-1]['event'],'unavailable')
        self.assertFalse(any(r['event']=='visibility' for r in rows))
    def test_invalid_state_is_not_coerced_to_visible(self):
        class Client:
            closed=False
            def poll(self,timeout):return [{'visible':8}]
            def close(self):self.closed=True
        client=Client();rows=[];observe(factory=lambda:client,emit=rows.append)
        self.assertTrue(client.closed);self.assertEqual(rows[-1]['errorType'],'ValueError')
    def test_event_budget_terminates_noisy_observer(self):
        class Client:
            closed=False
            def poll(self,timeout):return [{'visible':bool(i%2),'uptime':0} for i in range(32)]
            def close(self):self.closed=True
        client=Client();rows=[];observe(factory=lambda:client,clock=lambda:0,emit=rows.append)
        self.assertTrue(client.closed);self.assertEqual(rows[-1]['observations'],64)
    def test_registry_only_binds_input_manager_without_sending_input(self):
        client=VisibilityClient.__new__(VisibilityClient)
        client.globals=0;client.manager=None;client.manager_name=None;client.error=None
        client.manager_interface=None;calls=[]
        # Model the real callback's non-target path: unrelated globals must not bind.
        client._global(None,1,2,b'wl_compositor',4)
        self.assertIsNone(client.manager);self.assertIsNone(client.error)
        client.manager=3;client._global(None,1,4,b'wl_webos_input_manager',1)
        self.assertEqual(client.error,'RuntimeError')

    def test_state_requires_event_and_fresh_successful_poll(self):
        now=[0.];state=VisibilityState(clock=lambda:now[0])
        self.assertIsNone(state.current());state.update([]);self.assertIsNone(state.current())
        state.update([{'visible':False}]);self.assertIs(state.current(),False)
        now[0]=.6;self.assertIsNone(state.current())
        state.update([]);self.assertIs(state.current(),False)
        state.update([{'visible':True}]);self.assertIs(state.current(),True)
        state.clear();self.assertIsNone(state.current())
    def test_observer_clears_visibility_after_connection_failure(self):
        state=VisibilityState();rows=[]
        class Client:
            calls=0
            def poll(self,timeout):
                self.calls+=1
                if self.calls==1:return [{'visible':False,'uptime':0}]
                self.assertion();raise OSError('connection ended')
            def assertion(self):assert state.current() is False
            def close(self):pass
        observe(factory=Client,emit=rows.append,state=state)
        self.assertIsNone(state.current());self.assertEqual(rows[-1]['event'],'unavailable')

    def test_session_observer_survives_ten_minutes_and_diagnostic_budget(self):
        import threading
        now=[0.];state=VisibilityState(clock=lambda:now[0]);stop=threading.Event();rows=[]
        class Client:
            closed=False
            def poll(self,timeout):
                if now[0]==900:
                    assert state.current() is False
                    stop.set()
                now[0]+=1
                return [{'visible':bool(int(now[0])%2),'uptime':now[0]}]
            def close(self):self.closed=True
        client=Client()
        observe(factory=lambda:client,clock=lambda:now[0],state=state,
                duration=None,max_events=64,stop_event=stop,emit=rows.append)
        self.assertEqual(now[0],901);self.assertTrue(client.closed)
        self.assertIsNone(state.current())
        self.assertEqual(sum(r['event']=='visibility' for r in rows),64)
        self.assertFalse(any(r['event']=='unavailable' for r in rows))

    def test_monitor_reconnects_after_failure_and_clears_stale_state(self):
        from cursor_visibility_probe import VisibilityMonitor
        state=VisibilityState();clients=[]
        class Stop:
            stopped=False
            def is_set(self):return self.stopped
            def wait(self,seconds):
                assert state.current() is None
                return self.stopped
        stop=Stop()
        class Client:
            closed=False
            def __init__(self,index):self.index=index
            def poll(self,timeout):
                if self.index==0:
                    state.update([{'visible':True}]);raise OSError('disconnected')
                stop.stopped=True
                return [{'visible':False,'uptime':0}]
            def close(self):self.closed=True
        def factory():
            client=Client(len(clients));clients.append(client);return client
        monitor=VisibilityMonitor(state=state,factory=factory,emit=lambda r:None)
        monitor.stopped=stop;monitor.run()
        self.assertEqual(len(clients),2);self.assertTrue(all(c.closed for c in clients))
        self.assertIsNone(state.current())

    def test_monitor_close_stops_polling_and_releases_client(self):
        import threading
        from cursor_visibility_probe import VisibilityMonitor
        state=VisibilityState();polled=threading.Event()
        class Client:
            closed=False
            def poll(self,timeout):
                polled.set()
                threading.Event().wait(.01)
                return [{'visible':False,'uptime':0}]
            def close(self):self.closed=True
        client=Client();monitor=VisibilityMonitor(state=state,factory=lambda:client,emit=lambda r:None)
        monitor.thread.start()
        try:self.assertTrue(polled.wait(1))
        finally:monitor.close()
        self.assertFalse(monitor.thread.is_alive());self.assertTrue(client.closed)
        self.assertIsNone(state.current())
