"""Session persistence: an in-flight visit must survive a server restart/redeploy.

Sessions are held in memory only, so a `systemctl restart` (every deploy) or a
crash used to drop them and the kiosk's held id then 404'd "unknown session".
The server now snapshots each session to <data>/<sid>/session.json on every
mutation and reloads them (within TTL) at startup. These tests cover the
round-trip, TTL expiry, orphan sweep, and the LRU cap.
"""

from __future__ import annotations

import time

import pytest

import server.main as m
from core.context import IntakeAnswer, IntakeQuestion, SummaryDoc, UploadedFile


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "_PERSIST_SESSIONS", True)
    m.SESSIONS.clear()
    yield tmp_path
    m.SESSIONS.clear()


def _make(sid_lang="hi") -> m._Session:
    s = m._Session(sid_lang)
    # Populate a realistic mid-flow context.
    s.ctx.uploads.append(UploadedFile(id="ab12cd34", path="/x/raw/r.png", type="image"))
    s.ctx.summary = SummaryDoc(version=1, content={"lab_findings": [{"analyte": "Hemoglobin", "value": "9.6"}]})
    s.ctx.questions.append(IntakeQuestion(id=f"{s.ctx.session_id}:cond_anemia", pattern_id="cond_anemia", rendered_text="…"))
    s.ctx.answers.append(IntakeAnswer(question_id=f"{s.ctx.session_id}:cond_anemia", transcript="haan"))
    s.ctx.log("stage.test", detail="x")
    s.next_idx = 6
    s.stages["ocr"]["status"] = "done"
    s.last_activity = time.time()
    return s


def test_persist_and_restore_round_trip(data_dir):
    s = _make()
    sid = s.ctx.session_id
    m._persist_session(s)
    assert (data_dir / sid / "session.json").is_file()

    m.SESSIONS.clear()  # simulate a restart
    m._restore_sessions()

    assert sid in m.SESSIONS
    r = m.SESSIONS[sid]
    assert r.ctx.session_id == sid
    assert r.ctx.lang == "hi"
    assert [u.id for u in r.ctx.uploads] == ["ab12cd34"]
    assert r.ctx.summary is not None
    assert r.ctx.summary.content["lab_findings"][0]["analyte"] == "Hemoglobin"
    assert [q.pattern_id for q in r.ctx.questions] == ["cond_anemia"]
    assert [a.transcript for a in r.ctx.answers] == ["haan"]
    assert r.next_idx == 6
    assert r.stages["ocr"]["status"] == "done"


def test_expired_session_is_not_restored_and_dir_removed(data_dir):
    s = _make()
    sid = s.ctx.session_id
    s.last_activity = time.time() - (m.CFG.session_ttl_seconds + 60)  # stale
    m._persist_session(s)

    m.SESSIONS.clear()
    m._restore_sessions()

    assert sid not in m.SESSIONS
    assert not (data_dir / sid).exists()  # expired PHI swept


def test_orphan_dir_without_state_is_swept_when_stale(data_dir):
    d = data_dir / ("f" * 12)  # a valid-looking sid dir, no session.json
    d.mkdir()
    old = time.time() - (m.CFG.session_ttl_seconds + 60)
    import os
    os.utime(d, (old, old))

    m._restore_sessions()
    assert not d.exists()


def test_restore_respects_lru_cap(data_dir, monkeypatch):
    monkeypatch.setattr(m.CFG, "max_sessions", 2)
    sids = []
    for i in range(4):
        s = _make()
        s.last_activity = time.time() + i  # ascending recency
        m._persist_session(s)
        sids.append(s.ctx.session_id)

    m.SESSIONS.clear()
    m._restore_sessions()

    assert len(m.SESSIONS) == 2
    # The two most-recent survive; the two oldest were evicted + dirs removed.
    assert sids[2] in m.SESSIONS and sids[3] in m.SESSIONS
    assert not (data_dir / sids[0]).exists()
