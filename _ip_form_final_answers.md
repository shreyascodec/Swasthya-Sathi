Makes sense — a disclosure form for the Patent Mitra team doesn't need vendor/licence details, model sizes, or benchmark numbers, and leaving specific figures out actually keeps your claims broader. I've stripped all model licensing, model sizes (200 MB / 3.7 GB / the "8 GB" ceiling), and latency figures (131 s, ~1 s, 17 s, 65×, etc.), while keeping the architecture, safety mechanisms, and the Orin NX 16 GB device. Here's the whole updated set.

---

## APPLICANT DETAILS

**Patent Mitra Applicant Category** — **[YOU DECIDE]** — likely **Startup (DPIIT-Registered)** if DPIIT-recognised, else **Institute-led Biomedical Innovator**. Not ICMR Intramural/Extramural unless ICMR-funded.

**Address / Contact Number / Department/Division / Name of Signing Authority / Proposal ID** — **[YOU DECIDE]**

## CO-APPLICANT(S) / INVENTOR(S) / EXTERNAL FUNDING — **[YOU DECIDE]**
- Co-Applicants: Yes/No · Inventors: add yourself + co-inventors (required) · External Funding: likely **No** if no ICMR/grant money.

---

## TECHNICAL DETAILS — INVENTION DISCLOSURE

**Biomedical Domain** → **Yes** ✅

**Domain/Field of Invention** (dropdown) — **[YOU DECIDE]** — closest option (e.g. *Medical Devices / Digital Health / AI in Healthcare*).

**Subject Area** (dropdown) — **[YOU DECIDE]** — closest option (e.g. *Diagnostics / Health Informatics / Artificial Intelligence*).

**Title of Invention**
```
Offline Point-of-Care System and Method for Verifiable Digitisation of Laboratory Reports with Closed-Vocabulary Multilingual Voice Patient Intake
```

---

## DETAILS OF DISCLOSURE MADE SO FAR
**⚠️ FLAG:** Your code is/was in a **public GitHub repository** = a public disclosure with a running date (India = absolute novelty, no grace period). Raise with counsel. Leave Publication/Conference blank if no paper/talk.

---

## BACKGROUND OF INVENTION

**(a) What led you to create this invention / problems solved**
```
A patient at an Indian primary health centre (PHC) receives a printed laboratory report in English, full of abbreviations, with little explanation during a two-minute consultation, while a health worker manually re-types the values into a register. The invention is intended to solve the following problems: (1) Paper is a dead end - printed values cannot be searched, tracked or acted upon until a human copies them out, and manual copying introduces errors. (2) Language gap - the report is in English while the patient speaks Hindi or a regional language; explanation depends on whoever happens to be present. (3) No connectivity - PHCs and mobile health camps often have no reliable internet, so cloud AI services are unusable exactly where the need is greatest. (4) Privacy and cost - sending a patient's report to a cloud service creates a data-protection exposure and a per-page cost that does not scale to a public-health programme. (5) Generative AI is unsafe as-is - a language model summarising a report can invent values that were never on the page, and can silently drop values that were present; both are clinically dangerous and neither is visible to the user. (6) Free-form AI chat cannot be certified - if the system may say anything to a patient, no clinician will sign off on it and no regulator will approve it. (7) Small hardware, many models - the OCR, language, speech-to-text and speech synthesis models cannot all reside in the limited memory of a small edge device at once, and loading them naively makes per-patient processing too slow for a busy counter with a queue. (8) No evidentiary trail - a digital record produced later carries no proof of which source image and which software version produced it.
```

**(b) Current technologies / products / processes**
```
Existing solutions addressing parts of the same problem, and their limitations:
- Cloud document AI (e.g. Google Document AI, AWS Textract, Azure Form Recognizer): extract text and tables from documents via an API, but require internet and send patient data off-site.
- Cloud medical AI / generic large-language-model APIs used for report summarisation: summarise or explain a report, but are cloud-dependent and offer no guarantee against invented or lost values.
- Health kiosks / "health ATMs" (e.g. Yolo Health, Clinics on Cloud and similar Indian vendors): bundle vitals devices with a screen, but are typically cloud-backed.
- Indian single-modality AI-health point solutions (e.g. Qure.ai for radiology, SigTuple for microscopy, Tricog for ECG): each handles one modality and is mostly cloud or semi-connected.
- Symptom checkers (e.g. Ada, Infermedica): conduct free-form or decision-tree symptom questioning, not tied to the patient's actual report values.
- Speech stacks (e.g. Google Cloud STT/TTS, Bhashini, AI4Bharat models): provide Indian-language speech, but mostly as cloud APIs.
- Status quo in most PHCs: manual register entry plus a verbal explanation by staff, which is slow, error-prone and dependent on staff availability.
```

**(c) How does your invention address/improve on the drawbacks**
```
The invention differs by combining, on a single offline low-power edge device (for example an NVIDIA Jetson Orin NX with 16 GB unified memory, ARM):
- Fully offline operation: the active hardware profile declares "no internet", and the software then forces its AI libraries into offline mode at startup so that no component can silently reach the network.
- Data locality: nothing leaves the device, session artifacts are automatically deleted after an idle period, and there is zero marginal cost per patient after the hardware.
- Two-sided safety on the generated summary: a faithfulness check rejects any generated content not supported by the extracted source text (nothing is invented), while the extraction output is treated as the irreducible floor of the record (a measured value cannot be lost).
- Bounded speech safety: the system can only speak pre-approved, pre-translated questions from a clinician-signed question bank; it selects which to ask and fills patient-specific slots, but never composes free text.
- Predictable performance on small hardware: a model-residency policy keeps small always-needed models loaded and loads large models one at a time, and first-use initialisation is moved to device startup, so per-patient latency stays low and predictable rather than being paid by the first patient in the queue.
- Right-sized models: image typing uses a compact image classifier with an explicit reject class instead of a large vision-language model, which is far faster and lighter and refuses non-clinical input rather than guessing.
- No vendor lock-in: every model sits behind an interchangeable adapter selected by a configuration file, so swapping OCR or the language model is a configuration edit, not a code change.
- Provenance: every source file is hashed and the final record is sealed with a cryptographic (SHA-256) digest plus a version number.
```

---

## DETAILS OF INVENTION

**(a) Brief abstract**
```
A self-contained point-of-care device that turns a printed laboratory report into a structured, verifiable digital record and conducts a short spoken patient interview in the patient's own language, entirely without internet access.

The device photographs or ingests the report, cleans and quality-checks each page, decides whether the page is a document or a clinical photograph, reads printed values using on-device optical character recognition (or lifts the embedded text layer directly when the input is a digital PDF), and produces a structured summary using an on-device language model whose output is checked against the source so that nothing is invented and nothing measured is lost.

It then selects a small number of intake questions from a clinician-approved question bank, fills in patient-specific values from the extracted data only, speaks them aloud in the patient's language using an on-device neural voice (for Indic languages, phonemes for the closed question vocabulary may be precomputed and assembled at run time), captures spoken answers using on-device speech recognition with a language-verification safeguard, and seals the whole session - source hashes, extracted values, questions, answers, and software/model versions - into a versioned, integrity-stamped record.

All models run on a single low-power edge device (for example an NVIDIA Jetson Orin NX with 16 GB unified memory) under a residency policy that keeps only one heavy model resident at a time and keeps latency low and bounded, and every model choice is a configuration entry rather than hard-coded, so components can be replaced without altering the system.
```

**(b) 3–4 relevant keywords**
```
Offline edge-AI medical kiosk; on-device laboratory report digitisation and structuring; closed-vocabulary multilingual voice patient intake; verifiable AI clinical record (faithfulness and provenance)
```

**(c) Product / Process / Both** → **Both** ✅

**(d) Novel Features of invention**
```
1. Closed-vocabulary patient questioning: the set of sentences the machine can utter to a patient is finite, clinician-signed and pre-translated. The AI selects and fills slots; it never composes. This makes the safety guarantee structural rather than statistical, and adding a language does not widen the risk surface because no free-form text is generated at run time.
2. Two-sided guard on the generated summary: one check ensures nothing was invented (every claim traceable to extracted text); a second mechanism ensures nothing was lost (extraction output is the irreducible floor). Existing hallucination checks address only the first.
3. Bounded-latency multi-model residency policy: models are classed as pinned (small, always needed, never evicted) or heavy (large, loaded one at a time). Pinned models count against the memory ceiling but not against the limit on how many heavy models may be resident. Combined with a startup warm-up that runs one throwaway inference per model, per-patient latency becomes predictable.
4. Input routing before recognition: each page is classified as document or clinical photograph before OCR, and digital PDFs with a real text layer bypass the recognition engine entirely, so effort is not spent recognising text that either is not there or is already available.
5. Right-sized model per task: image typing uses a compact classifier with an explicit reject class rather than a large vision-language model - far faster and lighter, and it refuses non-clinical input instead of guessing.
6. Language-verification safeguard on speech recognition: the Hindi speech model can output Hindi even when the speaker speaks English, at full confidence - a silent failure. A second, independent model verifies the spoken language and raises a mismatch for review, so engine selection never rests on the primary model's own confidence.
7. Config-declared hardware profiles: one codebase adapts to a laptop, a cloud server or an ARM edge module by declaring device, memory ceiling, residency limits, precision and network permission in a profile; behaviour including offline enforcement follows from the profile.
8. Provenance sealing: source-file hashes, extracted values, question/answer pairs, and the identity and version of every model used are bound into one versioned record with a cryptographic (SHA-256) stamp.
9. Build-time phoneme precompute with run-time assembly for Indic voice: because the spoken content set is closed, the phoneme sequences for the question vocabulary are computed in advance and stored as a table; at run time the device assembles phonemes for the filled template and synthesises audio, so speech generation stays fast, deterministic and fully offline without running a heavy phonemiser on the device.
10. Audio-timing seam: each spoken clip is emitted with its precise duration, providing a clean attachment point for a future lip-synced avatar without changing the speech stage.
```

**(e) Use / Applications of invention**
```
- Primary health centres and pre-OPD triage: digitise the report and complete the intake interview before the patient reaches the doctor.
- Diagnostic laboratories: hand the patient a spoken explanation and the clinic a structured record at the collection counter.
- Rural and mobile health camps: works with no connectivity at all.
- Pharmacy and wellness kiosks: self-service report digitisation.
- Teleconsultation preparation: produce a structured record before a remote consult, so scarce doctor time is not spent on data entry.
- Public health programmes: bulk conversion of paper results into structured records at the point of collection.
- Home and elder care: a family member scans a report and hears it explained in the local language.
- Adjacent documents using the same machinery: discharge summaries, prescriptions, insurance claim documents, veterinary reports.
```

**(f) Alternatives to your invention**
```
1. Manual entry plus verbal explanation (today's baseline): slow, error-prone, and dependent on staff availability.
2. Cloud OCR plus a cloud LLM: technically capable, but requires connectivity, sends patient data off-site, costs per page, and offers no guarantee about invented or lost values.
3. A phone app that uploads a photo: same cloud dependencies, and assumes patient smartphone ownership and literacy.
4. A single large multimodal model doing everything in one pass: simpler to build, but too slow and too large for edge hardware, and it removes the checkpoints where safety is enforced.
5. A printed multilingual leaflet: cheap and safe, but generic and not tied to the patient's actual values.
6. A human interpreter or counsellor: best quality, but does not scale and is unavailable in most PHCs.
The invention is distinguished as the only option that is simultaneously offline, per-patient specific, bounded in what it may say, and evidentially sealed.
```

---

## HOW DOES THE INVENTION WORK
```
Nine stages run in a fixed order. Each stage acquires its model, does its work, and releases it - except models marked "pinned", which stay loaded. A single session record flows through all stages; stages communicate only through that record, never directly, which is what allows any stage or model to be replaced independently.

Physical arrangement: a camera/scanner and a microphone feed a single low-power edge compute unit (for example an NVIDIA Jetson Orin NX with 16 GB unified memory, ARM); a display and speaker output to the operator/patient; local encrypted storage holds session artifacts. There is deliberately no network connection. The system keeps a single heavy model resident at a time so it runs within the limited memory of a small edge device.

Stage 1 - Intake and preprocessing: photos and PDFs are received. PDF pages are rendered at a fixed resolution; photographs are normalised to a standard size. Each page is straightened and denoised. A quality gate measures sharpness and brightness and flags pages that must be re-scanned before anything else is attempted. A second gate measures how much of the page is near-white to decide document versus clinical photograph. A third check looks for a real embedded text layer in digital PDFs.

Stage 2 - Text extraction: pages carrying an embedded text layer pass their text forward without touching the recognition engine. Remaining document pages go through on-device OCR. Pages typed as clinical photographs are skipped. Each extracted field carries a confidence score; anything below a threshold is marked for human review. Results are cached against the page's content hash and the engine configuration, so re-processing an identical page is instant and changing the engine invalidates the cache automatically.

Stage 3 - Image typing: clinical photographs are classified into a small set of types by a compact classifier that includes an explicit reject class, so a scanned page or junk image is recorded as "unknown" rather than forced into a category.

Stage 4 - Faithful structuring: an on-device language model converts the extracted text into a structured record and a plain-language narrative. Generation is deterministic, and the output budget scales with how many values the page actually contains, so large reports are not truncated. The output is checked against the extracted text: claims not supported by the source cause the draft to be rejected or flagged. Separately, the extraction output is retained as the floor of the record, so a value the model omitted is still present downstream.

Stage 5 - Interpretation: reserved as a placeholder for a later, separate filing (clinician-validated reference ranges and abnormal-value flagging).

Stage 6 - Question selection: deterministic rules run over the structured facts - which tests are present, collection dates, medications named - and select a small number of questions from the clinician-signed bank, ordered by priority. Slots inside each question template are filled from extracted data only. A validation step confirms every selected question traces to a bank entry.

Stage 7 - Voice: each selected question is spoken in the patient's language by an on-device speech synthesiser - one path for Indic languages, another for English, chosen at run time from the session's language. For Indic closed-vocabulary utterances, phonemes are looked up from a precomputed table and assembled with the patient-specific value pieces, then passed to the neural voice model. Each clip is written as an audio file and recorded with its exact duration.

Stage 8 - Answer capture: the patient's spoken answer is transcribed on-device. A small independent model verifies that the language actually spoken matches the selected engine, and a mismatch is raised for review instead of being accepted.

Stage 9 - Sealing and record output: every source file is hashed. The structured values, narrative, questions, answers, model identities and versions are assembled into a versioned record and stamped with a cryptographic digest, then persisted.

Cross-cutting - model manager: all stages request models by role ("the OCR engine"), never by name. A manager resolves the role to a concrete engine, device and precision from configuration for the active hardware profile; enforces the memory ceiling; releases heavy models to make room; and refuses to load rather than crashing when memory is insufficient. At device startup a warm-up routine loads each model and performs one throwaway inference, publishing a readiness signal that holds the start button until the machine is genuinely ready.

Cross-cutting - offline enforcement: when the hardware profile declares no internet, the system sets its AI libraries into offline mode at startup, before any of them are loaded, so no component can attempt a network fetch.
```

---

## ADVANTAGES AND IMPROVEMENTS OVER EXISTING PRODUCT(S)/PROCESS
```
Speed and predictability:
1. Voice generation is far faster than a naive load-per-patient approach, with no meaningful loss of audio quality for the closed question set.
2. Image typing is far faster and lighter than the vision-language alternative.
3. The whole pipeline completes quickly for a typical report.
4. Latency is bounded, not merely fast: cold-start cost is paid once at device startup rather than by the first patient.
5. Repeat processing of an identical page is instant via content-hash caching.

Safety:
6. The machine cannot say an unapproved sentence to a patient.
7. Invented values are rejected; measured values cannot be lost.
8. Low-confidence extractions are flagged, not silently trusted.
9. Unrecognisable images are refused rather than guessed.
10. Silent language failure in speech recognition is caught by independent verification.
11. Poor-quality captures are stopped at the door with a re-scan instruction.

Privacy and cost:
12. No patient data leaves the device.
13. No per-patient cloud cost.
14. Session artifacts are automatically deleted after an idle period.
15. Works with zero connectivity.

Deployability and evidence:
16. One codebase spans laptop, server and ARM edge module by configuration.
17. Any model can be swapped without touching code - no vendor lock-in.
18. Every record is hashed, versioned and traceable to the exact software and model versions that produced it.
19. Runs on a single low-power ARM edge device (for example an NVIDIA Jetson Orin NX with 16 GB unified memory).
20. Speech for the closed question set is assembled from a precomputed phoneme table, so no heavy phonemiser runs on the device.
```

---

## STAGE / LEVEL OF DEVELOPMENT — **[YOU DECIDE]**
Two options only. Recommendation: **"Completed and results validated?"** (functioning end-to-end prototype). Pick "basic conceptualization" only if you read "validated" as *clinically* validated.

## USE OF BIOLOGICAL MATERIAL / TRADITIONAL KNOWLEDGE → **No** ✅

## COMMERCIALIZATION DATA
```
The inventors intend to develop and deploy this technology through a startup. Prospective deployment and commercialization channels include primary health centres and public-health programmes, diagnostic laboratory chains, and health-kiosk / "health ATM" operators seeking an offline, privacy-preserving, multilingual point-of-care solution.
```

## DISCLOSURE REGARDING RELATED WORK
**Related Invention** (multi-select) — **[YOU DECIDE]** (leave empty if none relate to a prior *ICMR* filing).

**If related to a previous ICMR invention** (background text box)
```
This invention is not derived from a previous ICMR-filed invention. Prior work by the inventors: an earlier version of the same pipeline with a different user interface, superseded by the current one. The clinical interpretation engine (reference ranges and abnormal-value flagging) is intended as a separate, later filing. The system integrates several off-the-shelf components (OCR, a language model, speech recognition and speech synthesis, and a compact image classifier trained by the inventors on their own synthetic dataset); none of these components is claimed as invented here - the invention is the overall architecture, the safety mechanisms and the orchestration.
```

## CONSENT — **[YOU]** tick both boxes.

---

That's the complete set with licensing, model sizes, and latency numbers removed. Want me to drop all of this into a `.docx` or `.md` file so you have it side-by-side while filling?