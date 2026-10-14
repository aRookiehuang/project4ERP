"""Cancellation callback is detached before a connection can be reused by another query."""

import threading


class QueryCancellation(threading.Event):
    def __init__(self):
        super().__init__()
        self._callback = None
        self._lock = threading.Lock()

    def attach(self, callback):
        with self._lock:
            self._callback = callback

    def detach(self):
        # Wait for an in-flight KILL before releasing the original connection.
        with self._lock:
            self._callback = None

    def set(self):
        already_set = self.is_set()
        super().set()
        if not already_set:
            threading.Thread(target=self._interrupt, daemon=True).start()

    def _interrupt(self):
        with self._lock:
            if self._callback:
                try:
                    self._callback()
                except Exception:
                    # Server MAX_EXECUTION_TIME and connection invalidation remain active.
                    pass
