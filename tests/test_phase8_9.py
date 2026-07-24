"""Phase 8-9 acceptance tests — hashing (source integrity) + report assembly.

Covers: the source-manifest digest fingerprints the exact input set and is
order-independent; the report bundles the clinical core + provenance; the report
hash is deterministic over content (timestamp-independent) and changes when a
value changes; versioning bumps on regeneration; and the audit stays PHI-free.
"""

from __future__ import annotations

from pathlib import Path

from core.context import (FinalReport, LabFlag, OCRField, OCRResult,
                          SessionContext, SummaryDoc, UploadedFile)
from core.pipeline import Pipeline
from stages.s8_hashing import source_manifest_digest
from stages.s9_report import assemble_content, content_digest


def _hashed_uploads() -> list[UploadedFile]:
    return [
        UploadedFile(id="a", path="a.png", type="image", sha256="a" * 64, is_document=True),
        UploadedFile(id="b", path="b.png", type="image", sha256="b" * 64, is_document=True),
    ]


def _ctx() -> SessionContext:
    ctx = SessionContext(session_id="p89", lang="hi")
    ctx.uploads = _hashed_uploads()
    ctx.summary = SummaryDoc(content={
        "facility": "Apollo", "doctor": "Dr X", "report_dates": ["12/05/2026"],
        "lab_findings": [{"analyte": "Hemoglobin", "value": "9.5", "unit": "g/dL",
                          "ref_range": "13.0-17.0", "source_field": "Hemoglobin"}],
        "medications": [{"name": "Tab Metformin 500mg"}],
        "narrative_en": "Hemoglobin is low.", "unknowns": [],
    })
    ctx.interpretations = [LabFlag(analyte="Hemoglobin", value="9.5", unit="g/dL",
                                   ref_range="12.0-17.0", status="low")]
    return ctx


# --- hashing / manifest ------------------------------------------------------

def test_manifest_is_order_independent() -> None:
    ctx = _ctx()
    d1 = source_manifest_digest(ctx)
    ctx.uploads = list(reversed(ctx.uploads))
    assert source_manifest_digest(ctx) == d1, "manifest must not depend on upload order"


def test_manifest_changes_when_a_source_changes() -> None:
    ctx = _ctx()
    d1 = source_manifest_digest(ctx)
    ctx.uploads[0].sha256 = "c" * 64
    assert source_manifest_digest(ctx) != d1


def test_hashing_fills_missing_upload_hash(tmp_path: Path) -> None:
    f = tmp_path / "x.png"; f.write_bytes(b"hello")
    ctx = SessionContext(session_id="h", lang="hi")
    ctx.uploads = [UploadedFile(id="x", path=str(f), type="image")]  # no sha256
    ctx = Pipeline(env_name="dev_4060").run_stage("hashing", ctx)
    assert ctx.uploads[0].sha256 and len(ctx.uploads[0].sha256) == 64
    assert any(e.action == "stage.hashing.done" for e in ctx.audit)


# --- report assembly / hashing / versioning ----------------------------------

def test_report_bundles_clinical_core_and_provenance() -> None:
    content = assemble_content(_ctx())
    assert content["lab_findings"] and content["interpretations"]
    assert content["medications"] and content["sources"]
    assert content["source_manifest_sha256"]
    # provenance carries per-file hashes
    assert all(s["sha256"] for s in content["sources"])


def test_report_hash_is_deterministic_over_content() -> None:
    c1 = assemble_content(_ctx())
    c2 = assemble_content(_ctx())
    assert content_digest(c1) == content_digest(c2), "same inputs must hash the same"


def test_report_hash_changes_when_a_value_changes() -> None:
    ctx = _ctx()
    d1 = content_digest(assemble_content(ctx))
    ctx.summary.content["lab_findings"][0]["value"] = "13.5"
    assert content_digest(assemble_content(ctx)) != d1


def test_report_stage_versions_and_hashes() -> None:
    pipeline = Pipeline(env_name="dev_4060")
    ctx = pipeline.run_stage("report", _ctx())
    assert isinstance(ctx.report, FinalReport)
    assert ctx.report.version == 1
    assert ctx.report.sha256 and len(ctx.report.sha256) == 64
    # regeneration bumps the version
    ctx = pipeline.run_stage("report", ctx)
    assert ctx.report.version == 2


def test_report_audit_is_phi_free() -> None:
    ctx = Pipeline(env_name="dev_4060").run_stage("report", _ctx())
    detail = next(e.detail for e in ctx.audit if e.action == "stage.report.done")
    # counts + version + hash prefix only — no analyte names or values
    assert "Hemoglobin" not in detail and "9.5" not in detail and "Apollo" not in detail
    assert "v1" in detail and "findings=1" in detail


def test_excluded_report_images_absent_from_report() -> None:
    """Report scans were never tagged, so the report's image_tags is empty here."""
    content = assemble_content(_ctx())   # both uploads are is_document, none tagged
    assert content["image_tags"] == []
