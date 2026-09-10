import json
import subprocess
import sys
import time

import pytest

from app import worker


@pytest.mark.parametrize("contents,code", [(None, 1), ("broken", 1), ("{}", 1)])
def test_missing_or_partial_heartbeat_is_unhealthy(tmp_path, monkeypatch, contents, code):
    path = tmp_path / "heartbeat.json"
    if contents is not None:
        path.write_text(contents)
    monkeypatch.setattr(worker, "HEARTBEAT", path)
    monkeypatch.setattr(sys, "argv", ["worker", "health"])
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == code


def test_health_check_avoids_loading_application_dependencies():
    # A fresh interpreter proves the frequent probe does not initialize the SDK
    # or ORM. This catches the cause of observed CPU-throttled probe timeouts.
    code = """
import sys
from app import worker
assert not {'boto3', 'sqlalchemy', 'fastapi'} & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=5)


@pytest.mark.parametrize("age,code", [(0, 0), (120, 1), (-120, 1)])
def test_heartbeat_freshness(tmp_path, monkeypatch, age, code):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({"loop": time.time() - age, "healthy": 0}))
    monkeypatch.setattr(worker, "HEARTBEAT", path)
    monkeypatch.setattr(sys, "argv", ["worker", "health", "--live"])
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == code
