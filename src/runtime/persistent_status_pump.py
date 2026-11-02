"""Existing event/generation checks with a reusable read-only polling client."""
from connected_status_pump import ConnectedStatusPump


class PersistentConnectedStatusPump(ConnectedStatusPump):
    def __init__(self, *, client_factory=None, **kwargs):
        if client_factory is None:
            from persistent_status_client import PersistentStatusClient
            client_factory = PersistentStatusClient
        self.client_factory = client_factory
        self.client = None
        self.client_closed = True
        super().__init__(poll=self._read_profiles, **kwargs)

    def _read_profiles(self):
        if self.client is None:
            raise RuntimeError('status client unavailable')
        return self.client.poll()

    def _poll(self):
        self.client_closed = False
        try:
            with self.client_factory(abort=self.stop_event.is_set) as client:
                self.client = client
                super()._poll()
            self.client_closed = True
        except Exception:
            self._fail()
        finally:
            self.client = None

    def stop(self, timeout=5):
        return super().stop(timeout=timeout) and self.client_closed
