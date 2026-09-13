import threading

from case_intelligence import readiness


def test_single_background_probe_never_blocks_readers_and_expires(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def probe():
        calls.append(1)
        entered.set()
        release.wait(5)
        return True
    monitor = readiness.CachedReadiness(probe, initial=True, interval=0.01)
    try:
        assert entered.wait(2)
        for _ in range(100):
            assert monitor.ready()
        assert len(calls) == 1
        monkeypatch.setattr(readiness, "monotonic", lambda: monitor._checked + 16)
        assert not monitor.ready()
    finally:
        release.set()
        monitor.close()
    assert not monitor._thread.is_alive()
    assert not monitor.ready()


def test_probe_failure_and_recovery_update_cached_readiness():
    state = [False]
    monitor = readiness.CachedReadiness(lambda: state[0], interval=100)
    try:
        monitor._refresh()
        assert not monitor.ready()
        state[0] = True
        monitor._refresh()
        assert monitor.ready()
        state[0] = False
        monitor._refresh()
        assert not monitor.ready()
    finally:
        monitor.close()
