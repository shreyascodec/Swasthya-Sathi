"""Model adapters — one thin file per impl, behind a common interface.

Each adapter registers itself with the ModelManager registry via
``register_adapter`` so ModelManager can swap impls purely from config.
Model-specific quirks stay inside the adapter.

Phase 0 ships only the ``dummy`` adapter used to prove VRAM load/unload.
"""

from models import dummy  # noqa: F401  (import for self-registration side effect)

# OCR engine adapters (Phase 2). Imports are lazy inside each adapter's
# _build_engine, so importing these modules does NOT pull in paddleocr/surya.
from models import ocr_paddle, ocr_rapid, ocr_stub, ocr_surya  # noqa: F401,E402

# Image-tag adapters (Phase 3). torch/torchvision imported lazily on load only.
from models import imagetag_medgemma, imagetag_mobilenet, imagetag_stub  # noqa: F401,E402

# LLM adapters (Phase 4). Ollama/Transformers deps imported lazily on load.
from models import llm_ollama, llm_stub, llm_transformers  # noqa: F401,E402
from models import llm_medgemma_mm  # noqa: F401,E402  (MedGemma text+image)

# STT adapters (Phase 6). faster-whisper imported lazily on load.
from models import stt_faster_whisper, stt_stub  # noqa: F401,E402

# TTS adapters (Phase 7). Final split: Kokoro-82M (Apache-2.0) for HINDI/Indic,
# Piper (MIT engine + MIT lessac voice) for ENGLISH; stub is the no-deps floor.
# Kokoro replaced Piper on Hindi because every Piper Hindi *voice* is
# non-commercial (CC-BY-NC-SA / IIT-M) — see commercial.md §0 / record.md §9.
# (IndicF5 / MMS / AI4Bharat FastPitch were benchmarked and removed.)
from models import tts_kokoro, tts_piper, tts_stub  # noqa: F401,E402
