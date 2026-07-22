"""Ghost sim fans must not stall the live poll loop."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory
from api.fanvue_connector import _retryable_request_exc
import requests


def test_junk_handles():
    assert fan_memory.is_junk_fan_handle("sim_llm_horny")
    assert fan_memory.is_junk_fan_handle("@sim_shy_slow")
    assert fan_memory.is_junk_fan_handle("test-fan-abc")
    assert not fan_memory.is_junk_fan_handle("socialist-chipmunk-765")
    assert not fan_memory.is_junk_fan_handle("patient-guineafowl-495")


def test_sim_uuid_not_real():
    from scripts.sim_mass import _sim_uuid

    u = _sim_uuid("llm-horny", 0)
    assert u.startswith("test-fan-")
    assert not fan_memory.is_real_fan_uuid(u)


def test_404_not_retried():
    resp = requests.models.Response()
    resp.status_code = 404
    exc = requests.HTTPError("404", response=resp)
    assert _retryable_request_exc(exc) is False

    resp500 = requests.models.Response()
    resp500.status_code = 500
    assert _retryable_request_exc(requests.HTTPError("500", response=resp500)) is True
