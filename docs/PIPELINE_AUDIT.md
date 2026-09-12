# Swasthya Sathi — Pipeline QA & Optimization Audit

Grounded review of all 9 stages + the avatar, from a **healthcare-safety, robustness, edge-case, and latency** lens, with concrete optimizations per stage.

- **Method:** full code read of every stage, a live end-to-end run for per-stage latency, edge-case probes against the running server, and the full test suite.
- **Test suite:** `177 passed, 2 failed` — both failures are **stale assertions vs. intentional config**, not regressions:
  - `test_phase0::test_dev_profile_is_8gb_one_model` expects `vram_ceiling_mb==8192`, config is `7500`.
  - `test_phase4::test_bench_runner_produces_artifacts` expects `4` LLM candidates, config has `6`.
- **Environment:** `env=local, device=cuda` (RTX 4060, 8 GB).

---

## 1. Measured latency (warm, 1-page synthetic Hindi report)

| Stage | Elapsed | Share | Notes |
|---|--:|--:|---|
| intake | 1.1 s | 8% | classical-CV: deskew → denoise → normalize |
| ocr | ~0 s | — | **masked**: hit text-layer/cache bypass; real RapidOCR cost unmeasured |
| image_tag | ~0 s | — | deferred load; skipped for report pages (correct) |
| **summary** | **12.7 s** | **88%** | **Phi-3.5 (Ollama) generation — the bottleneck** |
| interpret | ~0 s | — | pure rules |
| intake_qa | ~0 s | — | deterministic template select (STT is separate, on answer) |
| voice | 0.7 s | 5% | Kokoro, 5 clips, RTF ~0.03 |
| hashing | ~0 s | — | SHA-256 manifest |
| report | ~0 s | — | assemble + content digest |
| **Total** | **14.5 s** | | warm; cold warmup adds ~25–85 s (model loads) |
| avatar TTS | 85–260 ms / question | | re-synthesis + decode; RTF 0.03–0.05 |

**Headline:** one LLM call (summary) is ~88% of wall-clock. Everything else is effectively free. **This is the single optimization that matters**, and it *scales with report size* — a 16-page report (max_tokens up to 6144) will be far slower than this 1-page case. The 14.5 s is a best case; **real multi-page reports are the untested latency risk.**

---

## 2. Robustness — edge cases probed (live)

| Input | Behaviour | Verdict |
|---|---|---|
| No file, then process | `HTTP 400 "upload at least one file first"` | ✅ handled |
| Blank white / all black / 5×5 tiny | intake **flags** `needs_rescan` → pipeline **pauses** for review | ✅ handled |
| Corrupt bytes / empty file | intake **error** (`ValueError: could not read image`) → **pause: error**, recoverable via retry | ✅ handled |
| Pure noise image | **passes** quality gate (high Laplacian variance = "sharp"), OCR returns 0 fields | ⚠️ minor — garbage proceeds silently |

No crashes surfaced. Error handling lives at the **API layer** (run-stage pauses on error); `Stage.__call__` guarantees VRAM `unload` via `finally` even on exception. `Pipeline.run_all` (harness only) is unguarded — fine for the app path, worth an isolation wrapper for batch use.

---

## 3. Per-stage findings & optimizations

### [1] Intake & preprocess — `s1_intake.py`
- **Robustness:** solid. Idempotent (re-processed pages untouched); corrupt→error, blurry/dark→flag.
- **Healthcare:** quality-gate thresholds (`blur_laplacian_min=100`, `brightness 40–245`) are **not yet tuned on real Indian reports** (documented "open"). Risk: a valid phone photo of a real report wrongly flagged, or a bad one passed.
- **Edge gaps:** pure noise passes the gate; **no caps on page count / file size / dimensions** — a huge multi-page PDF (rendered at 200 DPI) or many uploads could exhaust memory/time.
- **Optimizations:**
  1. Add **input limits** (max pages, max bytes, max dimension) → DoS/OOM guard.
  2. `fastNlMeansDenoisingColored` is the ~1 s cost — **downscale-before-denoise** or skip denoise on already-sharp captures.
  3. Calibrate blur/brightness thresholds on a real-report sample; add a simple "is this text-bearing?" check to reject noise.

### [2] OCR — `s2_ocr.py`  ⚠️ highest clinical risk
- **Robustness:** excellent routing (skip / text-layer / cache / batched engine), stub fallback, corrupt-cache self-heal. `cv2.imread` can return `None` → passed to engine (verify engine tolerates None).
- **Healthcare (critical):** the **entire faithfulness chain assumes OCR read the numbers correctly** — the faithfulness gate checks the *summary matches OCR*, never that *OCR matches the paper*. A misread decimal (`9.5`→`95`) is a patient-safety error **no downstream gate can catch**. RapidOCR is configured **English-only** (`lang:[en]`); Hindi text on a report is missed. **OCR accuracy on real Indian printed reports is UNMEASURED** (documented "open") — this is the #1 validation gap for the whole product.
- **Optimizations:**
  1. **Bench RapidOCR vs Surya accuracy on real reports** (≥90% field target) — prerequisite to any clinical claim.
  2. Add a **numeric-plausibility sanity layer** (e.g., value within N× the printed ref-range, decimal-place sanity) to catch gross OCR misreads before they reach interpretation.
  3. Real OCR latency is unmeasured here (cache/synthetic) — measure on real pages; `det_limit_side_len=1280` already caps cost.

### [3] Image tagging — `s3_imagetag.py`
- **Robustness/latency:** exemplary — **deferred model load** (only when a real clinical photo is present), so report-only sessions pay 0. Stub fallback; unknown/low-score → `unknown`.
- **Healthcare:** the MobileNetV3 head is **trained on the SYNTHETIC bench set — NOT clinically validated**; predictions are meaningless until retrained on real consented images. No-diagnosis invariant enforced (type/quality only).
- **Optimization:** perf is fine. The work item is **clinical**: retrain on real data before any claim; keep MedGemma zero-shot as the fallback until then.

### [4] Summary — `s4_summary.py`  ← the latency bottleneck
- **Robustness:** JSON-length truncation handled (max_tokens scales with value count to 6144); faithfulness gate **drops hallucinations** (value↔analyte binding); stub fallback on CPU.
- **Healthcare:** the safety core, and **well-engineered** — faithfulness binding prevents a value being lifted from another analyte; `drop_hallucinations` keeps the stored summary OCR-faithful.
- **Optimizations (biggest lever in the whole pipeline):**
  1. **Constrained/JSON decoding** — use Ollama `format: json` (or a grammar) so the model can't emit unparseable output → fewer retries, fewer tokens.
  2. **Stream** the generation so the UI shows progress instead of a 13 s freeze (perceived latency).
  3. **Right-size the model** — Phi-3.5 3.8B Q4 is the cost; candidates `qwen2.5:1.5b` exist. A/B faithfulness+quality vs. latency; a smaller model may halve summary time if faithfulness holds.
  4. **Cap narrative length** — the English narrative is clinician-only (never spoken/translated per config); a terser, more structured narrative cuts tokens directly.
  5. **Watch multi-page scaling** — instrument summary latency vs. value count; 16-page reports are the real risk.

### [5] Interpret — `s5_interpret.py`
- **Robustness/latency:** pure rules, ~0 s. **Best safety engineering in the codebase**: OCR-floor **union** (no LLM omission can drop a value), **narrative-contradiction detector** (flags LLM prose that disagrees with the deterministic verdict), no-diagnosis (status only), `unknown` when uncertain.
- **Healthcare gaps:**
  1. LabQAR reference table (277 analytes) is **auto-generated, PENDING CLINICIAN REVIEW** — an unverified critical threshold could mis-flag or miss a critical value.
  2. **Context-blind:** sex-aware ranges exist but `ctx.patient_sex` is absent in POC, and no age is captured — so sex/age-specific ranges (Hb, creatinine, etc.) use generic defaults → possible mis-flags.
- **Optimizations:** perf N/A. Priorities: **clinician sign-off on the table**, and **capture patient sex/age at intake** to unlock correct ranges.

### [6] Intake Q&A — `s6_intake_qa.py`
- **Robustness/latency:** deterministic template selection from a **closed, clinician-reviewable bank** (off-bank is structurally impossible), ~0 s. STT stub fallback; re-answer **replaces** (no stale duplicate).
- **Healthcare:** strong — no free-form LLM questions; grounded in extracted facts. Transcribed answers are advisory (clinician sees them).
- **Optimizations:** measure **Vaani STT latency/accuracy** on real patient speech; expand bank coverage (cap is 5 questions).

### [7] Voice — `s7_voice.py`
- **Robustness/latency:** 0.7 s for 5 clips (Kokoro warm, `keep_warm`), stub fallback.
- **Healthcare:** Apache-2.0 Hindi Kokoro; questions spoken in patient language; summary deliberately **not** spoken (clinician-only English text).
- **Optimization:** the **avatar re-synthesizes** questions the voice stage already synthesized (double TTS). Reuse the voice stage's clips + a persisted alignment instead of re-calling `/api/avatar/tts` → removes a redundant synth per question.

### [8] Hashing — `s8_hashing.py`
- **Robustness/latency:** ~0 s. Order-independent SHA-256 manifest; tamper-evident.
- **Healthcare:** integrity, **not confidentiality** (by design). See cross-cutting privacy below.

### [9] Report — `s9_report.py`
- **Robustness/latency:** ~0 s. `content_digest` excludes timestamp → reproducible/de-dupable; provenance block (per-file hashes + manifest).
- **Optimization:** perf N/A. Future: PDF (WeasyPrint/Devanagari) + FHIR bundle for ABDM (planned).

---

## 4. Cross-cutting

- **Privacy / PHI at rest (healthcare gap):** uploads, audio, transcripts, and summaries are stored **plaintext** under `_session_data` (`encrypt_at_rest: false`). A TTL reaper deletes them (good), but there's **no encryption at rest or secure deletion**. For a clinic handling patient data, add at-rest encryption + shredding. Audit trail correctly carries **type/version/counts only, never PHI**.
- **Concurrency:** one global `PIPELINE_LOCK` serializes all work — correct for a single kiosk, but a second patient blocks. Fine for the POC; note for multi-lane deployments.
- **Access control:** no auth on the API (localhost kiosk, single user) — acceptable for the kiosk model, flag if ever multi-user/networked.
- **The three clinical-validation gaps that gate any medical claim** (all documented in-code as "open"): (1) OCR accuracy on real reports, (2) LabQAR threshold review, (3) image_tag real-data training. **None are code bugs — they are validation work.**

---

## 5. Prioritized backlog

**P0 — patient safety / clinical validity**
1. Bench **OCR accuracy** on real Indian reports; add a numeric-plausibility sanity check on extracted values.
2. **Clinician review** of the LabQAR reference/critical-threshold table.
3. **Capture patient sex/age** at intake → correct sex/age-specific reference ranges.

**P1 — latency & robustness**
4. Summary: **JSON-constrained decoding + streaming**; A/B a smaller model; instrument multi-page scaling.
5. Intake: **input caps** (pages/size/dimensions); calibrate quality thresholds; reject noise.
6. **Encrypt PHI at rest** + secure deletion.

**P2 — polish**
7. Avatar: reuse voice-stage audio + alignment (drop double TTS).
8. Fix the 2 stale tests (7500 ceiling, 6 candidates).
9. Retrain image_tag on real consented images.

---
*Living document — extend per stage as real-report samples and clinician review land.*
