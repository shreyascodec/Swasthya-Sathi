# Swasthya Sakhi → Maternal & Child Health (Mothers) — Pivot Log

**Date:** 2026-09-12
**Goal:** Repoint the deployed Swasthya Sakhi kiosk (https://swasthyasathi.brenin.co, GCP
`swasthya-sakhi`, `SS_ENV=cloud_flagship`) from the generic lab-report flow to
**Maternal (antenatal) Health Risk Prediction for remote areas**, currently focused on
mothers. Child/newborn is a later phase.

> ⚠️ All clinical thresholds, tiering rules, and referral wording in this pivot are
> **POC placeholders PENDING CLINICIAN REVIEW**, drawn from public WHO / ICMR / DIPSI /
> MoHFW-PMSMA guidance. They must be confirmed by an OB-GYN / PMSMA reviewer before any
> real use. Every value is a config edit — never a code change (see the questionnaire in
> chat for what to confirm).

## Design principle (unchanged)
The 9-stage pipeline, the OCR → faithfulness-gated summary → **deterministic** interpret →
voice Q&A → report scaffold, and the safety invariants (no-diagnosis, no autonomous
escalation, values must trace to source) are all **reused as-is**. The maternal pivot is a
**config-selected mode** plus one new deterministic risk module — the lab path is untouched
on other profiles, and all lab-mode tests still pass.

## What changed

### 1. Maternal threshold table (new) — `data/mch/maternal_thresholds.yaml`
Same YAML shape the interpret engine already loads, so per-parameter status
(low/normal/high/critical) is computed by the existing pure lookup. Parameters + cited
placeholder cut-offs:
| Parameter | high | critical | source |
|---|---|---|---|
| Hemoglobin (g/dL) | <11.0 (low) | <7.0 | WHO pregnancy anaemia |
| Systolic BP (mmHg) | ≥140 | ≥160 | ACOG/WHO pre-eclampsia |
| Diastolic BP (mmHg) | ≥90 | ≥110 | ACOG/WHO |
| Fasting Blood Sugar (mg/dL) | ≥92 | ≥126 | IADPSG |
| Blood Sugar / 2h OGTT (mg/dL) | ≥140 | ≥200 | DIPSI |
| Pulse (bpm) | >100 / <60 | ≥120 | — |
| Temperature (°C) | ≥37.5 | ≥39.0 | maternal sepsis |
| Platelets (lakh/cumm) | <1.5 | <1.0 | HELLP |

### 2. Maternal risk module (new) — `stages/maternal_risk.py`
Pure, deterministic. Sits on top of the per-parameter statuses and adds what the numeric
engine can't: a combined **blood-pressure** reading (`150/100`), a **urine-protein** grade
(`++`), and the patient's **danger-sign answers**. Produces a **risk tier**:
- **HIGH** — any critical value, severe BP (≥160/110), severe anaemia (<7), OR any reported
  danger sign. *Mandatory red-flag overrides — can never be suppressed.*
- **MODERATE ("Needs attention")** — any high/low value, none critical.
- **LOW** — all measured values normal, no danger signs.
- **UNKNOWN** — nothing readable to assess.
Each tier carries a recommended **action** (HIGH → refer to FRU/CHC + 108; MODERATE → MO +
follow-up ANC; LOW → routine ANC), a **reasons** list, and a **red_flags** list.

### 3. Interpret stage — `stages/s5_interpret.py`
When `interpret.mode == maternal`, after computing the deterministic flags it calls
`assess_maternal_risk(...)` (vitals only) and stores the result in
`ctx.summary.content["maternal_risk"]`. Lab mode is unaffected.

### 4. Report stage — `stages/s9_report.py`
Recomputes `maternal_risk` **with the danger-sign answers folded in** (a reported danger
sign can escalate the tier to HIGH), and includes it in the sealed report bundle.

### 5. Antenatal question bank (new) — `data/question_bank/maternal_patterns.yaml`
Replaces the generic intake bank in maternal mode. Universal **danger-sign screen** (always
asked, never capped): severe headache/blurred vision, vaginal bleeding, reduced fetal
movement, sudden severe swelling, fever — plus grounded follow-ups (low Hb, high sugar).
A new `danger_sign` trigger type was added to `stages/intake_qa_rules.py`; danger-sign
pattern ids start with `danger_` so the risk module can escalate a "yes".

### 6. OCR extraction — `stages/ocr_extract.py`
Added an additive **blood-pressure capture** pass (`_BP_RE`) so a combined `150/100 mmHg`
behind an explicit BP label becomes a field (the numeric value patterns can't cross the
`/`). Lab-safe: only fires on an explicit BP label.

### 7. Config — `config/stages.cloud_flagship.yaml`
Maternal mode is enabled **only on the live cloud_flagship profile** (reversible, keeps
tests green):
```yaml
interpret:
  mode: maternal
  reference_path: data/mch/maternal_thresholds.yaml
intake_qa:
  bank_path: data/question_bank/maternal_patterns.yaml
  max_questions: 6
```

### 8. Backend API — `server/main.py`
Snapshot `derived.maternal_risk` now exposes the risk object to the frontend.

### 9. Frontend (new Swasthya Sakhi UI — `C:\Users\shrey\Downloads\Swasthya Sakhi`)
- `src/api/client.ts` — added `MaternalRisk` type + `derived.maternal_risk`.
- `src/state/PipelineContext.tsx` — exposes `maternalRisk`.
- `src/components/MedicalSummary.tsx` — rewritten as a **maternal risk report**: coloured
  risk-tier banner, recommended action, red-flag list, measured-values grid, and the real
  danger-sign responses.
- `src/screens/SummaryScreen.tsx` — removed the false "shared with doctor via ABHA" card.
- `src/i18n/translations.ts` — added risk-tier/action strings (hi+en) and reframed the
  welcome / summary / upload copy to maternal.

## Verification
- Lab-mode regression: `tests/test_phase5.py` + `tests/test_phase6.py` → **69 passed**.
- Maternal logic (local): thresholds, risk tiering (moderate / high / severe-BP / danger-sign
  escalation), and question selection all correct; non-medical doc → no questions.
- **End-to-end on the live VM** (synthetic ANC card: BP 150/100, Hb 8.4, Sugar 165):
  extracted all three → risk tier **"Needs attention"** with correct reasons + referral
  action, and generated the 5 danger-sign questions + grounded anaemia question.
- UI build: `tsc` clean, bundle built.

## Deployment status
- **Backend / pipeline / models / config: DEPLOYED & LIVE** on `swasthya-sakhi` (maternal
  mode confirmed active, end-to-end tested).
- **UI dist: DEPLOYED (2026-09-12)** — bundle `index-B9HYBfo9.js`; welcome/summary copy
  reframed to maternal; risk-tier banner + referral action + danger-sign responses confirmed
  present in the served bundle and rendering live. Pre-maternal UI backed up on the VM at
  `frontend/dist.mch.bak`.

### Live UI = PIPELINE / OPERATOR view (for the stakeholder demo, 2026-09-12)
Switched the live UI from the polished end-user kiosk to the repo's **pipeline/operator
view** (`frontend/` App.tsx stage stepper, Swasthya-Saathi style) — stakeholders wanted to
see the pipeline working, not the consumer flow. Added a **maternal RISK panel** to the
interpret stage (`frontend/src/StageBody.tsx`) reading `derived.maternal_risk`, plus the
`MaternalRisk` type in `frontend/src/api.ts`. Rebuilt on the VM (`~/swasthya/frontend` →
`dist`). Also added a `Cache-Control: no-cache` middleware on the HTML shell in
`server/main.py` so redeploys always show on reload (no stale kiosk mid-demo).

Demo flow: choose language → Upload the ANC card/report → step through the 9 stages; each
shows its real output, and the **maternal risk tier + referral action + reasons** appear in
the interpret stage.

### Loose ends
- The maternal end-user **kiosk UI source** lives at `C:\Users\shrey\Downloads\Swasthya
  Sakhi` (its own git repo) — only its build is on the VM. Move it into this repo to
  version-control it. To show the kiosk instead of the pipeline view, deploy its dist;
  rebuilding the repo `frontend` reverts to the pipeline view.
- Nothing committed yet — backend maternal mode, UI changes, and this log are uncommitted on
  branch `v2`.

## Known gaps / next (need the domain-expert answers)
- **Urine protein** ("++") is captured by the risk module but the summary LLM sometimes
  drops a value with no number/unit — confirm ANC-card layout and consider a dedicated
  extraction pass.
- Pre-eclampsia composite (raised BP **+** proteinuria → HIGH even if neither is "critical")
  is a clinician-tuning decision, currently MODERATE.
- Gestational-age–specific thresholds (1st vs 3rd trimester), postnatal/newborn scope, and a
  real de-identified MCP-card test set — pending the questionnaire responses.
- Longitudinal patient record (visit-to-visit) and referral loop-closure are out of scope
  for this demo.
