import threading

from backend.app.cancellation import QueryCancellation


def test_cancel_callback_runs_once_and_detaches_before_reuse():
    token = QueryCancellation()
    called = threading.Event()
    count = []

    def interrupt():
        count.append(1)
        called.set()

    token.attach(interrupt)
    token.set()
    assert called.wait(1)
    token.detach()
    token.set()
    assert count == [1]


def test_detached_connection_is_not_interrupted():
    token = QueryCancellation()
    called = threading.Event()
    token.attach(called.set)
    token.detach()
    token.set()
    token._interrupt()
    assert not called.is_set()
