# Swasthya Sathi — Website & Product Content Guide

> **Source of truth:** This document extracts product information that is present in the Swasthya Sathi codebase and project documentation (`README.md`, `DEPLOY.md`, `_patent_figures/DISCLOSURE.md`, `config/`, `frontend/`, `server/`, `stages/`, `data/`). It does **not** invent features, statistics, clients, testimonials, or medical claims beyond what the project itself states.
>
> **Product status:** Pipeline proof-of-concept (POC) — React + FastAPI wrapping a nine-stage offline lab-report pipeline. Not a marketed clinical device claim set; LabQAR flagging is marked pending clinician review in config.

---

## 1. Product overview

**Name (Hindi):** स्वास्थ्य साथी  
**Name (English):** Swasthya Sathi  
**Positioning subtitle (UI):** Point-of-care  
**App / API titles:** “Swasthya Sathi” (browser title); “Swasthya Sathi API” (FastAPI)

**One-line description (from UI tagline):**

> Your health companion. Upload a lab report and get a clear, spoken explanation in your language.

**Abstract (from invention disclosure):**

A self-contained point-of-care device that turns a printed laboratory report into a structured, verifiable digital record and conducts a short spoken patient interview in the patient’s own language, entirely without internet access.

**What it is today:** An offline-first kiosk-style POC. The React SPA drives a FastAPI backend that runs a fixed nine-stage Python pipeline: report intake → OCR → image tagging → structured summary → lab interpretation → intake Q&A → spoken questions → integrity hashing → versioned sealed report (“स्वास्थ्य साथी रिपोर्ट”).

**Deployment model:** One self-contained box — FastAPI server, local models (OCR, Ollama summary LLM, Kokoro/Piper voice), and Chrome on the same machine. In kiosk mode the server serves the built SPA and the API from a single origin on port `8000`.

---

## 2. Purpose and problem statement

Problems the project explicitly aims to address (from `_patent_figures/DISCLOSURE.md`):

1. **Paper is a dead end.** Printed lab values cannot be searched or acted on until someone retypes them; manual copying introduces errors.
2. **Language gap.** Reports are typically English; patients often speak Hindi or another regional language.
3. **No reliable connectivity.** PHCs and camps often lack internet, making cloud AI unusable where need is high.
4. **Privacy and cost.** Sending report photos to cloud services creates data-protection exposure and per-page cost.
5. **Unsafe generative summarisation.** An LLM can invent values that were never on the page, or drop values that were.
6. **Uncertifiable free-form chat.** If the system may say anything to a patient, clinical sign-off and regulatory approval are difficult.
7. **Small hardware, many models.** OCR, LLM, STT, and TTS cannot all stay loaded on an ~8 GB device without careful residency control.
8. **No evidentiary trail.** Digital records need proof of which source image and software/model versions produced them.
9. **Voice licensing risk.** High-quality Hindi voices may be non-commercial-only or pull in copyleft phonemizers unsuitable for a shipped product.

---

## 3. Features and modules

### 3.1 End-to-end pipeline (nine stages)

| # | Stage (code) | UI label | What it does |
|---|--------------|----------|--------------|
| 1 | `intake` | Intake & image quality | Accept PDF/images; render/normalize; deskew/denoise; blur/brightness quality gate; document vs clinical photograph; PDF text-layer detection |
| 2 | `ocr` | Text extraction (OCR) | On-device OCR (or PDF text-layer path); field extraction with confidence; cache by page hash |
| 3 | `image_tag` | Image tagging | Classify clinical photos: skin / eye / wound / oral (+ reject → unknown). Type + quality only — **never a diagnosis** |
| 4 | `summary` | Report summary | Structured “स्वास्थ्य साथी रिपोर्ट” draft + English narrative; faithfulness check vs OCR |
| 5 | `interpret` | Lab interpretation | Rule-based Low / Normal / High / critical flags from LabQAR reference ranges |
| 6 | `intake_qa` | Intake questions | Select top-N questions from a closed, pre-translated question bank |
| 7 | `voice` | Voice generation | TTS for selected questions (summary is **not** spoken in current variant) |
| 8 | `hashing` | Integrity hashing | SHA-256 source manifest |
| 9 | `report` | Final report | Versioned, content-hashed sealed report bundle |

### 3.2 Product invariants (explicit in code/docs)

- The system may only ask questions from the clinician-reviewable bank — it must **never invent a question**.
- Image tagging is **type + quality only**, never a diagnosis.
- Faithfulness: summary values must trace to OCR; invented claims are rejected/flagged.
- Extraction is the **floor**: values OCR found but the LLM omitted are recovered/flagged so they are not lost.
- Lab **flags** (rule-based interpretation) are treated as authoritative over the LLM narrative when they disagree (UI warning).
- OCR configured **English-only** for printed reports (project note: ~99% of reports are pure English).

### 3.3 Operator UI modules (React SPA)

No multi-page router. Phase-driven single SPA:

1. **Welcome** — brand + language selection  
2. **Upload** — drag/drop or browse lab report files  
3. **Process** — horizontal stage stepper + focus card; pause gates for quality/errors  
4. **Questions** — live spoken Q&A (`LiveQA`) when pipeline pauses for intake  
5. **Report** — result hero, expandable stage timeline, audit trail  

Flow rail labels: **Upload → Process → Questions → Report**.

### 3.4 Supporting engineering modules (not patient-facing)

- `core/` — Stage ABC, SessionContext, ModelManager, EnvProfile, Pipeline  
- `models/` — adapters for OCR, LLM, STT, TTS, image-tag  
- `config/` — `models.yaml`, `stages.yaml`, env profiles  
- `data/labqar/` — reference ranges  
- `data/question_bank/` — intake patterns  
- `bench/` — model bake-off harness  
- `tests/` — acceptance / stage harness  
- `deploy/` — systemd unit, Windows startup script  

---

## 4. User flows

### 4.1 Primary kiosk flow (implemented)

1. Browser opens the app (dev: Vite `:5173`; kiosk: `http://localhost:8000`).
2. UI connects to backend; shows “Connecting to pipeline…” then welcome.
3. Operator/patient chooses language (**Hindi** or **English**; others shown as “soon”).
4. **Start →** moves to upload.
5. Upload one or more pages: JPG, PNG, BMP, TIFF, WEBP, or PDF.
6. UI waits for model readiness (“Warming up…”); **Process** enabled when ready.
7. Pipeline runs stage-by-stage. Quality/error gates may pause for Continue / Retry / Stop.
8. After voice stage, pipeline pauses for **intake Q&A**: each question is spoken; patient records a spoken answer; STT transcribes; re-record replaces answer; Skip / Next / Finish & seal report.
9. Hashing + final report seal.
10. Results screen: faithfulness %, analyte count, flagged count, Q&A progress; expandable stages; audit trail.
11. **Done — start next patient** creates a new session.

### 4.2 Session continuity

- Session id stored in `sessionStorage` (`ss_sid`).
- Browser refresh **reattaches** to the in-memory session if still live.
- Process restart clears in-memory sessions (fresh start).
- Idle sessions and `_session_data/<id>/` are reaped after TTL (default 1800 s).

### 4.3 Pause / resume actions

- `continue` — proceed after a non-error gate  
- `retry` — retry a failed stage  
- `stop` — halt the run  

---

## 5. User roles

**No application-level roles, login, or RBAC are implemented.**

| Concept | Reality in codebase |
|---------|---------------------|
| Patient | Conceptual — answers spoken questions; language selected for them |
| Doctor / clinician | Conceptual — flags and English narrative are for clinician review; no doctor login |
| Kiosk operator | Same SPA flow; no separate operator account |
| Audit `actor` | Defaults to `"system"` |
| OS `User=kiosk` | systemd service account only — not an app role |

---

## 6. Use cases

Stated applications in the invention disclosure (intended contexts, not deployed customer list):

- Primary health centres and pre-OPD triage  
- Diagnostic laboratories (spoken explanation + structured record at counter)  
- Rural and mobile health camps (no connectivity)  
- Pharmacy and wellness kiosks (self-service digitisation)  
- Teleconsultation preparation (structured record before remote consult)  
- Public health programmes (paper → structured records at collection)  
- Home and elder care (family scans a report; hears explanation in local language)  
- Adjacent document types mentioned as same machinery: discharge summaries, prescriptions, insurance claim documents, veterinary reports  

**Baseline alternative called out in disclosure:** manual register entry + verbal explanation by staff.

---

## 7. Healthcare workflows

### 7.1 Lab report digitisation path

1. Capture or upload printed/digital lab report (photo or PDF).  
2. Quality gate → rescan if too blurry / wrong brightness.  
3. Route: PDF text layer → skip OCR; document page → OCR; clinical photo → image tag (no OCR).  
4. Structure findings + English narrative with faithfulness gate.  
5. Flag analytes Low/Normal/High/critical via LabQAR ranges.  
6. Select up to **5** intake questions (config `max_questions`).  
7. Speak questions; capture answers.  
8. Seal versioned report with SHA-256 content digest + source hashes.

### 7.2 Lab interpretation (LabQAR)

- Reference table: `data/labqar/reference_ranges_labqar.yaml` (~277 analytes; generated from a LOINC-mapped xlsx with curated POC critical thresholds + Indian aliases).  
- Config note: **PENDING CLINICIAN REVIEW**.  
- Alternate smaller curated table: `data/labqar/reference_ranges.yaml`.  
- High-priority statuses surfaced for the doctor: `critical` (config).  
- Status pills in UI: status values such as low / normal / high / critical.

### 7.3 Closed intake question bank

Categories present in `data/question_bank/patterns.yaml` (version `poc-1`):

| Category | Examples |
|----------|----------|
| Condition follow-up | High glucose / HbA1c, renal, anemia, liver, lipids, thyroid, vitamin D, B12, medication adherence |
| Gap | Stale report older than configured months (default 6) |
| Missing companion test | Missing HbA1c when glucose high; missing lipid when sugar high |
| Standard history | Chief complaint, current meds, symptom duration, allergies, chronic conditions |

Templates exist in **English and Hindi**; slots (`{analyte}`, `{value}`, `{unit}`, `{date}`, `{drug}`) filled from extracted data only.

### 7.4 Clinical image path

Classes: **skin, eye, wound, oral**; non-clinical / junk → **unknown**.  
Product copy: “Type + quality only — never a diagnosis.”  
Primary classifier: MobileNetV3-Small fine-tuned head — **trained on synthetic bench set; not clinically validated** (config warning: retrain on real consented images before clinical claims). MedGemma available as fallback candidate.

### 7.5 Explicitly not present

- Device vitals capture (BP, SpO₂, etc.)  
- Appointments / scheduling  
- EMR / HIS sync  
- Multi-clinic admin dashboard  
- Patient or clinician accounts  
- Prescription writing or treatment recommendations as a product feature  

---

## 8. Dashboard and reports

### 8.1 What exists (per-session operator UI)

Not a multi-patient operations dashboard. After a run finishes:

**Result hero**

- “Report ready”  
- Stage completion count + report version  
- Stats: Faithfulness %, Analytes, Flagged, Answers (answered/total)

**Pipeline stages timeline**

- Expandable per-stage detail (intake thumbs, OCR fields, image tags, summary draft, interpretation table, questions/answers, audio clips, hashes, final JSON)

**Audit trail**

- Table: time / actor / action / detail (type/version oriented; report audit avoids PHI content in log detail)

### 8.2 Sealed report content (JSON)

Assembled fields include:

- `patient_language`, `facility`, `doctor`, `report_dates`  
- `lab_findings`, `interpretations`, `medications`, `narrative_en`  
- `image_tags`, `intake` (question + answer pairs), `unknowns`  
- `sources` (file basename, sha256, type, is_document)  
- `source_manifest_sha256`  
- Report `version` + content `sha256`  

On disk (when `SS_PERSIST_REPORTS=1`): `_session_data/<id>/report_v<n>.json` until session reap.

### 8.3 Planned report exports (not implemented)

Documented as future work in `stages/s9_report.py`:

- PDF export via WeasyPrint (Devanagari) — dependency commented in `requirements.txt`  
- FHIR-ish JSON bundle for an ABDM path  

`bench/` produces bake-off charts/CSV/markdown for model comparison — engineering tooling, not a product dashboard.

---

## 9. Digital Human / AI capabilities

### 9.1 AI capabilities (implemented)

| Capability | Implementation notes |
|------------|----------------------|
| LLM summary | Primary: Ollama `qwen2.5:3b-instruct` (text-only; images not fed to summary in current variant) |
| Faithfulness gate | Scores/rejects unsupported LLM claims vs OCR |
| Image typing | MobileNetV3-Small (primary); MedGemma candidate fallback |
| STT | faster-whisper Vaani Hindi CT2 INT8 primary; multilingual large-v3; small router for language mismatch |
| TTS Hindi | Kokoro-82M (`hf_alpha` voice), Apache-2.0 path, CUDA-pinnable |
| TTS English | Piper `en_US-lessac-medium` |
| Model manager | Role-based adapters; pinned vs heavy residency; env VRAM ceilings |
| Warmup | Startup load + readiness gate so first patient is not cold |

LLM candidates listed in config (not all primary): Sarvam-1, MedGemma-4B, Airavata-7B.

### 9.2 Digital Human / avatar

| Item | Status |
|------|--------|
| Wav2Lip avatar | **Deferred** — `avatar.enabled: false` in `config/models.yaml` (“voice-only for now”) |
| Lip-sync seam | Each audio clip can carry `duration_ms` for a future avatar attachment (disclosure claim 10) |
| 3D / talking-head UI | **Not present** in the React UI |
| Brand mark in UI | Clipboard emoji `📋` — not a digital human |

---

## 10. Voice and language support

### 10.1 UI languages

| Code | Label | Status |
|------|-------|--------|
| `hi` | हिन्दी / Hindi | **Available** |
| `en` | English | **Available** |
| `mr` | मराठी / Marathi | Shown — “coming soon” |
| `bn` | বাংলা / Bengali | Shown — “coming soon” |
| `ta` | தமிழ் / Tamil | Shown — “coming soon” |
| `te` | తెలుగు / Telugu | Shown — “coming soon” |

Prompt copy: “Choose your language · अपनी भाषा चुनें”

### 10.2 Voice behaviour (current variant)

From `config/stages.yaml`:

- `speak_summary: false` — summary is **not** read aloud  
- `translate_summary: false` — summary stays English for the clinician  
- `speak_questions: true` — intake questions spoken in patient language  
- `max_clips: 12`

### 10.3 Speech capture UX

- Autoplay question audio; on-screen text  
- “Tap to record your answer” / “Recording — tap to stop”  
- Mic constraints: echo cancellation, noise suppression, auto gain, 16 kHz mono  
- Language-verification safeguard (router) flags mismatch for review (disclosure / STT config)

### 10.4 Licensing note (product-relevant)

Hindi TTS chose Kokoro because Piper Hindi *voices* are non-commercial; Piper remains for English. Disclosure describes optional build-time phoneme precompute so a copyleft phonemizer need not ship on the kiosk.

---

## 11. APIs and integrations

### 11.1 HTTP API (FastAPI — `server/main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/ready` | Warmup readiness (`ready`, `warming`, `loaded`, `unavailable`, `seconds`) |
| `POST` | `/api/session` | Create session `{ lang }` |
| `GET` | `/api/session/{sid}` | Session snapshot |
| `POST` | `/api/session/{sid}/upload` | Multipart file upload |
| `POST` | `/api/session/{sid}/run-stage` | Run next pipeline stage |
| `POST` | `/api/session/{sid}/resume` | `continue` / `stop` / `retry` |
| `POST` | `/api/session/{sid}/answer` | STT answer audio + `question_id` |
| `GET` | `/api/file?path=` | Serve session artifacts (Range/206 for audio) |
| `GET` | `/` | Built SPA (`frontend/dist`) when present |

API version string in app metadata: `1.0.0`.

### 11.2 Runtime integrations / dependencies

| Integration | Role |
|-------------|------|
| **Ollama** (local) | Summary LLM host (`qwen2.5:3b-instruct`); Docker reaches host via `host.docker.internal` |
| **Local weights** | `models/weights/` — STT, TTS, image-tag, OCR models |
| **Hugging Face cache** | e.g. Kokoro; MedGemma gated (dev setup may need HF login — not end-user auth) |
| **PaddleOCR / PaddleX** | On-device OCR |
| **Chrome / browser** | Kiosk UI |

### 11.3 Not integrated (as of this codebase)

- Cloud Document AI / medical APIs as primary path  
- ABDM / ABHA live connectors (FHIR-ish export only planned)  
- External EMR, payment, SMS, WhatsApp  
- Authentication providers (OAuth/JWT)  

Sessions are **in-memory** (TTL + LRU). README layout mentions `db/` SQLite, but that folder is **not present** in the tree reviewed for this document.

---

## 12. Technical stack (high level)

### Frontend

- React 19 + TypeScript  
- Vite 8  
- Oxlint  
- No React Router / UI kit dependency  

### Backend / pipeline

- Python: FastAPI + uvicorn  
- Pipeline: custom Stage / ModelManager architecture  
- OCR: PaddleOCR + paddlepaddle  
- CV: OpenCV, PyMuPDF  
- LLM client: Ollama (primary); transformers candidates  
- STT: faster-whisper  
- TTS: Kokoro (Hindi), Piper (English)  
- Config: PyYAML, pydantic  
- Tests: pytest  

### Environments (`SS_ENV`)

| Profile | Intent |
|---------|--------|
| `dev_4060` | RTX 4060 8 GB; offline-first; max 1 heavy GPU model |
| `cloud` | Larger VRAM budget; internet allowed; encrypt_at_rest |
| `orin` | Jetson Orin NX (ARM) production target; offline-first; encrypt_at_rest |

### Packaging / ops

- Docker multi-stage build → NVIDIA CUDA runtime; image `swasthya-app:latest`; port 8000  
- `deploy/swasthya-sathi.service` (Linux systemd)  
- `start_kiosk.bat` / Windows scheduled-task installer  
- Server env vars: see `.env.example` (`SS_HOST`, `SS_PORT`, `SS_WARMUP`, `SS_SESSION_TTL_SECONDS`, `SS_MAX_SESSIONS`, `SS_PERSIST_REPORTS`, …)

---

## 13. Benefits

Benefits stated by the project (disclosure / design docs) — not external marketing claims:

**Safety**

- Cannot utter unapproved patient sentences (closed question bank)  
- Invented summary values rejected; measured values cannot be silently lost  
- Low-confidence OCR flagged  
- Unrecognisable images refused rather than forced into a class  
- Language mismatch on STT raised for review  
- Poor captures stopped with rescan instruction  

**Privacy & cost**

- Offline-first profiles force AI libs offline when configured  
- Patient data does not leave the device in the offline design  
- No per-patient cloud OCR/LLM cost after hardware  
- Session artifacts auto-deleted after idle TTL  

**Deployability & evidence**

- One codebase across laptop / cloud / Orin via config  
- Model swap by YAML, not code  
- Versioned, SHA-256 sealed records with model/source provenance  
- Targets commodity ~8 GB-class hardware  

**Latency (measured on development hardware — from disclosure)**

- Voice step reduced from ~131 s to under ~2 s (warm path; same device)  
- Image typing ~65× faster / ~18× smaller than vision-language alternative  
- Typical pipeline ~17 s cited for a typical report on the development laptop profile  
- Cold-start cost moved to device warmup  

---

## 14. FAQs

Answers reflect codebase behaviour only.

**Q: What is Swasthya Sathi?**  
A: An offline point-of-care POC that digitises a lab report, builds a faithfulness-checked structured record, flags lab values with reference ranges, and asks a short set of spoken intake questions in Hindi or English.

**Q: Does it diagnose disease?**  
A: Image tagging is explicitly type + quality only, never a diagnosis. Lab flags are rule-based Low/Normal/High/critical overlays pending clinician review — not a substitute for a doctor.

**Q: Does it work without internet?**  
A: Yes by design on `dev_4060` and `orin` profiles (`internet_allowed: false`). Local Ollama and on-device weights are required. The `cloud` profile allows internet for weight fetch at deploy time.

**Q: Which languages work today?**  
A: Hindi and English. Marathi, Bengali, Tamil, and Telugu appear in the UI as “coming soon.”

**Q: Will it read the full report aloud?**  
A: Not in the current variant. Voice is for intake questions only; the summary narrative stays English text for the clinician.

**Q: What file types can I upload?**  
A: JPG, JPEG, PNG, BMP, TIFF, WEBP, PDF (multi-page supported).

**Q: Is there a login?**  
A: No. Sessions are anonymous UUIDs in memory.

**Q: Where is my data stored?**  
A: In-memory session plus `_session_data/<session_id>/` for uploads/audio/reports. Idle sessions are deleted after the configured TTL. Optional sealed `report_v<n>.json` until reap.

**Q: Can the AI invent lab numbers?**  
A: The faithfulness stage checks summary claims against OCR and flags/rejects unsupported values. Recovered OCR values missing from the LLM findings are surfaced so omissions do not hide results.

**Q: Is there a talking avatar / digital human?**  
A: Not enabled. Wav2Lip is deferred (`enabled: false`). Audio duration metadata exists as a future lip-sync seam.

**Q: Does it connect to ABDM / FHIR today?**  
A: No live ABDM integration. A FHIR-ish JSON export is listed as future work on the sealed report content.

**Q: Who is this for?**  
A: Disclosure targets PHCs, labs, camps, pharmacy/wellness kiosks, teleconsult prep, and similar offline point-of-care settings — the shipped UI is a single shared kiosk flow.

---

## 15. SEO-ready product descriptions, taglines, and CTAs

> Use only claims consistent with the POC. Avoid “FDA approved,” outcome statistics, or named customers unless added from real sources later.

### Brand names

- स्वास्थ्य साथी  
- Swasthya Sathi  
- Swasthya Sathi · Point-of-care  
- स्वास्थ्य साथी रिपोर्ट  

### Taglines (existing + faithful variants)

| Type | Text |
|------|------|
| Primary (UI) | Your health companion. Upload a lab report and get a clear, spoken explanation in your language. |
| Short | Your health companion. |
| Product | Offline point-of-care lab report digitisation and spoken intake. |
| Technical | Capture → extract → faithful structure → closed-vocabulary voice intake → sealed record. |
| Hindi prompt | अपनी भाषा चुनें |

### Meta description candidates (≤160 chars, grounded)

1. Swasthya Sathi turns printed lab reports into structured, verifiable records and asks spoken intake questions in Hindi or English—offline on one device.  
2. Point-of-care health companion: upload a lab PDF or photo, get faithfulness-checked findings, lab flags, and a short spoken Q&A—no cloud required.  
3. Offline AI kiosk POC for Indian clinics: OCR, safe summarisation, LabQAR flags, and clinician-banked Hindi/English intake questions.

### H1 / H2 website copy suggestions

- H1: स्वास्थ्य साथी — Swasthya Sathi  
- H2: Point-of-care lab reports, explained in your language  
- H2: From paper report to sealed digital record  
- H2: Spoken intake questions a doctor can trust  

### CTA button labels (from UI + natural extensions)

| Existing in UI | Suggested reuse |
|----------------|-----------------|
| Start → | Primary landing CTA |
| Process ▶ / Process N file(s) ▶ | Upload screen |
| Continue ▶ | Gate resume |
| Tap to record your answer | Q&A |
| Finish & seal report ▶ | End of Q&A |
| Done — start next patient | Post-report |
| Browse files | Upload |
| Start over | Error recovery |

Suggested marketing CTAs consistent with product: **Start in your language**, **Upload a lab report**, **See how the pipeline works**.

### Keyword themes present in project materials

Offline edge AI medical kiosk · Laboratory report digitisation · Closed-vocabulary multilingual voice intake · Verifiable AI clinical record · Faithfulness and provenance · Point-of-care · Hindi TTS · PHC / camp / lab counter  

---

## 16. Existing assets

| Asset | Path | Notes |
|-------|------|-------|
| Favicon (linked) | `frontend/public/icon.svg` | Referenced from `index.html` |
| Favicon (extra) | `frontend/public/favicon.svg` | Present in public/ |
| Icon sprite | `frontend/public/icons.svg` | Vite/template-related icons |
| Hero PNG | `frontend/src/assets/hero.png` | Vite template asset; not the branded welcome hero |
| Vite SVG | `frontend/src/assets/vite.svg` | Template |
| Brand mark | UI emoji `📋` | No custom logo image file for the product mark |
| Brand colour | `#11A05C` | `--accent` in `frontend/src/index.css` |
| Patent Fig. 1–5 | `_patent_figures/fig{1-5}_{labeled\|clean}.png` | System, pipeline, model manager, intake, voice precompute |
| Disclosure | `_patent_figures/DISCLOSURE.md` | Invention narrative |
| Figure generator | `_patent_figures/make_figures.py` | Regenerates patent figures |
| TTS listen samples | `_kokoro_*_samples/`, `_indicf5_samples/` | Engineering listen-test WAVs |
| Clinical image benches | `data/clinical/{eye,skin,wound,oral,junk}/` | Evaluation assets |
| Docker model bake-ins | `.docker/hf-cache/`, `.docker/paddlex/` | Kokoro / PaddleX weights for images |

---

## 17. Limitations

Documented or evident from the codebase:

1. **POC / pipeline demo**, not a finished multi-tenant SaaS product.  
2. **No authentication or role-based access.**  
3. **No persistent multi-patient database** in the running server (in-memory sessions; README `db/` not present).  
4. **LabQAR ranges pending clinician review.**  
5. **Image tagger not clinically validated** (synthetic training set).  
6. **OCR English-only** by configuration.  
7. **Only Hindi and English** fully available in UI.  
8. **Summary not spoken or translated** in current voice variant.  
9. **Avatar / Wav2Lip deferred.**  
10. **No PDF or FHIR/ABDM export yet.**  
11. **No vitals devices, appointments, or EMR sync.**  
12. **Requires local GPU-friendly stack + Ollama** for full behaviour; warmup can list models as `unavailable` if weights/Ollama missing.  
13. **Referenced docs missing from tree** (e.g. `REACT_UI.md`, `ARCHITECTURE.md`, `PLAN.md`, `commercial.md`) — do not assume their content for marketing.  
14. **Streamlit** remains in requirements historically; active UI is React.  
15. Public repository noted in disclosure as a **novelty / filing timing** concern for counsel — business/legal, not a clinical feature.

---

## 18. Implemented, partial, and planned features

### Implemented

- Nine-stage pipeline with real adapters (intake through sealed report)  
- React kiosk UI: welcome, upload, process, live Q&A, results, audit  
- FastAPI session/upload/stage/resume/answer/file/ready/health API  
- Faithfulness checking and OCR-floor recovery messaging  
- LabQAR rule-based interpretation against YAML ranges  
- Closed EN/HI question bank with deterministic triggers  
- Hindi Kokoro TTS + English Piper TTS for questions  
- faster-whisper STT answer capture with language router config  
- Model warmup + readiness gate  
- Session TTL reap + optional report persistence  
- Env profiles: `dev_4060`, `cloud`, `orin`  
- Docker compose GPU service; systemd / Windows kiosk deploy scripts  
- Offline enforcement seam via env profile  

### Partial / constrained

- Multilingual UI: six languages shown; **two** enabled  
- Image tagging: plumbing validated; **clinical validation pending**  
- Lab interpretation: ranges loaded; **clinician review pending**  
- Summary: English narrative for clinicians; patient-facing spoken summary **off**  
- Avatar timing seam (`duration_ms`) without avatar runtime  
- `encrypt_at_rest` flag exists on cloud/orin profiles (local `dev_4060` false)  
- STT IndicConformer entry stubbed in config (`stt.indic`)  
- README mentions SQLite `db/` — **not present** in current tree  

### Planned / deferred (explicit in repo)

- Wav2Lip digital human / avatar (`enabled: false`)  
- Marathi, Bengali, Tamil, Telugu language enablement  
- WeasyPrint PDF export (Devanagari)  
- FHIR-ish / ABDM JSON bundle  
- Clinical interpretation as a **separate patent filing** (disclosure scope note)  
- Retrain image-tag head on real consented images  
- Speak/translate summary (config flags exist but set false)  

---

## 19. Business and positioning information inferable from the project

| Topic | Inference grounded in repo |
|-------|----------------------------|
| Product category | Offline edge / point-of-care health kiosk for lab-report digitisation + intake |
| Primary markets (stated intent) | Indian PHCs, diagnostic labs, camps, pharmacy/wellness kiosks, teleconsult prep, public health programmes |
| Commercial voice constraint | Engines and voice *data* chosen for commercial-clean licensing (Kokoro Hindi; Piper English) |
| Hardware target | Dev on RTX 4060 8 GB laptop; production target Jetson Orin NX 16 GB |
| Cloud | Optional `cloud` env for demos; not the privacy-first path |
| Competitive landscape (disclosure only) | Contrasted with cloud Document AI, health ATMs (e.g. Yolo Health, Clinics on Cloud), modality AIs (Qure.ai, SigTuple, Tricog), symptom checkers, Bhashini/AI4Bharat, ABDM ecosystem — listed for patent context, **not** as customer claims |
| IP posture | Invention disclosure draft + figures prepared; interpretation engine scoped as possible separate filing; public repo flagged to counsel |
| Monetisation | Not specified in code; cost argument is “zero marginal cloud cost per patient after hardware” |
| Brand | Bilingual Hindi-first naming; green accent `#11A05C`; emoji clipboard mark pending a formal logo asset |

---

## 20. Key source files for content owners

| Need | Path |
|------|------|
| Product overview / run | `README.md` |
| Kiosk deploy & privacy | `DEPLOY.md` |
| Problem / novelty / applications | `_patent_figures/DISCLOSURE.md` |
| UI copy & flows | `frontend/src/App.tsx`, `LiveQA.tsx`, `StageBody.tsx` |
| Stage tuning | `config/stages.yaml` |
| Model registry | `config/models.yaml` |
| Question bank | `data/question_bank/patterns.yaml` |
| Lab ranges | `data/labqar/` |
| Report schema | `stages/s9_report.py` |
| API surface | `server/main.py` |
| Server knobs | `.env.example` |

---

*Generated for website and product content use. Update this file when features move from planned → implemented, when clinician-reviewed assets replace pending tables, or when formal brand assets replace the emoji mark.*
