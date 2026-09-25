"""Avatar session-reaper / billing-control tests.

These cover the fixes that stop a walked-away or crashed kiosk visit from billing
Brenin per-second until a distant ceiling:

* idle reap  — a session with heartbeats that then go silent is ended after
  ``_AVATAR_IDLE_S`` (the primary abandoned-visit control);
* no idle reap for sessions that never beat (older kiosk builds) — max-age only;
* max-age reap — the crashed-tab backstop;
* end-by-both-ids — the reaper/end path tries session_id AND session_token, so a
  Brenin /end that keys on the token no longer fails silently and keeps billing;
* untrack-by-token — clearing tracking by either id, so the orphan sweep isn't
  permanently blocked by a stale entry;
* /api/avatar/heartbeat — bumps activity, no-ops for unknown sessions.

The Brenin network layer is fully stubbed; no real calls are made.
"""

from __future__ import annotations

import time

import pytest

import server.main as m


@pytest.fixture(autouse=True)
def _clean_tracking():
    with m._avatar_lock:
        m._avatar_active.clear()
    yield
    with m._avatar_lock:
        m._avatar_active.clear()


@pytest.fixture
def ended(monkeypatch):
    """Record every conversation id the reaper/end path tries to end, and treat
    the call as a network success so `ended` counts increment."""
    calls: list[str] = []

    def fake_end(cid: str) -> bool:
        calls.append(cid)
        return True

    monkeypatch.setattr(m, "_end_conversation", fake_end)
    # Ensure the reaper's key gate ("no key -> do nothing") is open.
    monkeypatch.setattr(m, "_BRENIN_KEY", "test-key", raising=False)
    # No orphan sweep in these unit tests unless a test opts in.
    monkeypatch.setattr(m, "_brenin_raw", lambda *a, **k: (200, {"data": []}))
    return calls


def test_idle_session_is_reaped(ended):
    m._track_avatar_session("sid1", "tok1")
    # It beat once, but the last beat is now older than the idle ceiling.
    with m._avatar_lock:
        m._avatar_active["sid1"]["last_beat"] = time.time() - (m._AVATAR_IDLE_S + 5)

    n = m._reap_avatar_sessions()

    assert n == 1
    assert "sid1" in ended  # ended by id...
    assert "tok1" in ended  # ...and by token
    with m._avatar_lock:
        assert "sid1" not in m._avatar_active  # untracked


def test_never_beaten_session_is_not_idle_reaped(ended):
    # Fresh session, no heartbeat yet, well under the max-age ceiling.
    m._track_avatar_session("sid2", "tok2")

    n = m._reap_avatar_sessions()

    assert n == 0
    assert ended == []
    with m._avatar_lock:
        assert "sid2" in m._avatar_active  # a live consult is left alone


def test_max_age_session_is_reaped_even_without_heartbeat(ended):
    m._track_avatar_session("sid3", "tok3")
    with m._avatar_lock:
        m._avatar_active["sid3"]["started"] = time.time() - (m._MAX_AVATAR_SESSION_S + 5)

    n = m._reap_avatar_sessions()

    assert n == 1
    assert "sid3" in ended and "tok3" in ended


def test_heartbeat_defers_reap(ended):
    m._track_avatar_session("sid4", "tok4")
    # Idle for a while...
    with m._avatar_lock:
        m._avatar_active["sid4"]["last_beat"] = time.time() - (m._AVATAR_IDLE_S + 5)
    # ...but a fresh beat (by token) arrives before the reaper runs.
    assert m._beat_avatar_session("tok4") is True

    assert m._reap_avatar_sessions() == 0
    with m._avatar_lock:
        assert "sid4" in m._avatar_active


def test_untrack_by_token_clears_entry():
    m._track_avatar_session("sid5", "tok5")
    m._untrack_avatar_session("tok5")  # end path only knew the token
    with m._avatar_lock:
        assert "sid5" not in m._avatar_active


def test_beat_unknown_session_is_noop():
    assert m._beat_avatar_session("nope") is False


def test_heartbeat_endpoint(ended):
    from fastapi.testclient import TestClient

    m._track_avatar_session("sid6", "tok6")
    with TestClient(m.app) as client:
        r = client.post("/api/avatar/heartbeat", json={"session_id": "sid6"})
        assert r.status_code == 200 and r.json()["ok"] is True

        r2 = client.post("/api/avatar/heartbeat", json={"session_id": "ghost"})
        assert r2.status_code == 200 and r2.json()["ok"] is False

    with m._avatar_lock:
        assert m._avatar_active["sid6"]["last_beat"] is not None


def test_end_endpoint_ends_both_ids_and_untracks(ended):
    from fastapi.testclient import TestClient

    m._track_avatar_session("sid7", "tok7")
    with TestClient(m.app) as client:
        r = client.post("/api/avatar/end", json={"session_id": "sid7", "session_token": "tok7"})
        assert r.status_code == 200 and r.json()["status"] is True

    assert "sid7" in ended and "tok7" in ended
    with m._avatar_lock:
        assert "sid7" not in m._avatar_active
