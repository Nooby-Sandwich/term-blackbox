import socket
import time

import pytest

from blackbox import recorder


@pytest.fixture
def sock_pair():
    """Two connected sockets (no real network)."""
    a, b = socket.socketpair()
    a.settimeout(5)
    b.settimeout(5)
    yield a, b
    for s in (a, b):
        try:
            s.close()
        except OSError:
            pass


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Point the recorder at a temp directory so tests never touch ./logs."""
    monkeypatch.setattr(recorder, "LOG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def box(log_dir):
    return recorder.BlackBox(rows=5, cols=40)


@pytest.fixture
def wait_for():
    """wait_for(lambda: condition) -> True once it holds, False after timeout."""

    def _wait(condition, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.01)
        return condition()

    return _wait
