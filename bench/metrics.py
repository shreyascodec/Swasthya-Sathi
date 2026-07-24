"""Scoring for the summary bake-off.

- faithfulness / hallucination: delegated to the product's faithfulness checker
  (the same gate the stage enforces) — this is the safety headline.
- extraction accuracy: precision/recall/F1 of predicted lab findings vs gold.
- hindi quality (proxy): Devanagari density + coverage of grounded values in the
  Hindi narrative. NOTE: a proxy for triage/ranking; final Hindi quality needs a
  clinician read (flagged as such in the report).
"""

from __future__ import annotations

import re

from stages.faithfulness import check_faithfulness
from stages.summary_schema import SummarySchema

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def faithfulness(summary: SummarySchema, ocr_fields) -> float:
    return check_faithfulness(summary, ocr_fields).faithfulness


def extraction_prf(pred: SummarySchema, gold: dict) -> dict:
    gold_pairs = {(_norm(g["analyte"]), _norm(str(g["value"])))
                  for g in gold.get("lab_findings", [])}
    pred_pairs = {(_norm(f.analyte), _norm(f.value)) for f in pred.lab_findings}
    if not pred_pairs and not gold_pairs:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    tp = len(pred_pairs & gold_pairs)
    precision = tp / len(pred_pairs) if pred_pairs else 0.0
    recall = tp / len(gold_pairs) if gold_pairs else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def devanagari_ratio(text: str) -> float:
    # Denominator counts letters AND combining marks so matras/danda in the
    # Devanagari count don't push the ratio above 1.0.
    base = [c for c in (text or "") if _LETTERS.match(c) or _DEVANAGARI.match(c)]
    if not base:
        return 0.0
    deva = _DEVANAGARI.findall(text or "")
    return min(1.0, len(deva) / len(base))


def hindi_quality(pred: SummarySchema, gold: dict) -> float:
    """0..1 proxy for Hindi-narrative quality (Hindi items only).

    LEGACY: the summary is English-only now — the patient-language surface is
    generated at the voice boundary (stages/s7_voice.py), so summaries no
    longer carry a Hindi narrative and this scores 0. Kept so old bench
    configs/reports still run; a voice-stage translation bench would replace it.
    """
    narrative = getattr(pred, "narrative_hi", "") or ""
    ratio = devanagari_ratio(narrative)
    gold_values = [str(g["value"]) for g in gold.get("lab_findings", [])]
    covered = sum(1 for v in gold_values if v in narrative)
    coverage = covered / len(gold_values) if gold_values else 1.0
    return round(min(1.0, 0.5 * ratio + 0.5 * coverage), 4)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
