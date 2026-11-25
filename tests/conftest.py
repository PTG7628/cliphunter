import os
import shutil
import socket
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="cliphunter_test_")
os.environ["CLIPHUNTER_DATA"] = os.path.join(_TMP, "data")
os.environ["CLIPHUNTER_APPROVED"] = os.path.join(_TMP, "approved")
MEDIA = os.path.join(ROOT, "tests", ".media")
os.makedirs(MEDIA, exist_ok=True)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def mock_ai():
    from tests import mock_ai as m
    port = _free_port()
    m.start(port)
    import time
    time.sleep(0.8)
    return {"url": f"http://127.0.0.1:{port}/v1", "calls": m.calls}


@pytest.fixture(scope="session")
def env(mock_ai):
    from core import config, db
    db.init()
    return {"ai": mock_ai, "tmp": _TMP}


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
