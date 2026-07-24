"""MedGemma-4B multimodal LLM adapter (text, or text + report page images).

Same ModelManager contract as the other LLM adapters, but MedGemma is a
vision-language model, so this adapter also accepts page IMAGES alongside the
OCR text — the configuration the bake-off recommended for multi-page report
consolidation (see bench/runner_mm.py, reportstake.md). Loaded INT4 to fit 8 GB.

`generate(system, user)` is the plain text path used by the summary stage today.
`generate(system, user, images=[...])` additionally attaches page images; the
stage only takes that path when `summary.use_images` is on AND images exist.

Setup (on the 4060): pip install torch transformers accelerate bitsandbytes;
huggingface-cli login and accept the MedGemma license.
"""

from __future__ import annotations

from core.model_manager import register_adapter
from models.llm_base import LLMAdapterBase, LLMUnavailable


class MedGemmaMMAdapter(LLMAdapterBase):
    default_vram_mb = 3700
    multimodal = True

    def _build(self):
        try:
            import torch
            from transformers import (AutoModelForImageTextToText, AutoProcessor,
                                      BitsAndBytesConfig)
        except ImportError as exc:  # pragma: no cover - env dependent
            raise LLMUnavailable(
                "transformers/torch/bitsandbytes not installed for MedGemma "
                "multimodal. `pip install torch transformers accelerate "
                "bitsandbytes`, or swap llm to stub_llm."
            ) from exc

        compute_dtype = torch.bfloat16 if self.is_gpu else torch.float32
        quant_cfg = None
        if self.spec.get("quant", "int4").startswith("int4") and self.is_gpu:
            quant_cfg = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=compute_dtype,
            )
        processor = AutoProcessor.from_pretrained(self.model_id)
        model = AutoModelForImageTextToText.from_pretrained(
            self.model_id, quantization_config=quant_cfg,
            device_map="auto" if self.is_gpu else None, dtype=compute_dtype,
        )
        model.eval()
        return {"processor": processor, "model": model, "torch": torch}

    def generate(self, system: str, user: str, max_tokens: int = 1024,
                 temperature: float = 0.0, images=None) -> str:
        self.load()
        return self._generate_mm(system, user, max_tokens, temperature, images)

    def _generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        # Text-only path (satisfies the base contract).
        return self._generate_mm(system, user, max_tokens, temperature, None)

    def _generate_mm(self, system: str, user: str, max_tokens: int,
                     temperature: float, images) -> str:
        processor = self._handle["processor"]
        model = self._handle["model"]
        torch = self._handle["torch"]

        user_content = []
        opened = []
        if images:
            from PIL import Image
            for img in images:
                pil = Image.open(img).convert("RGB") if isinstance(img, str) else img
                opened.append(pil)
                user_content.append({"type": "image", "image": pil})
        user_content.append({"type": "text", "text": user})

        messages = [
            {"role": "system", "content": [{"type": "text", "text": system}]},
            {"role": "user", "content": user_content},
        ]
        inputs = processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(model.device)
        # repetition_penalty guards against greedy-decode loops (the model can
        # otherwise emit the same finding forever until it hits max_new_tokens).
        gen_kwargs = {"max_new_tokens": max_tokens, "do_sample": temperature > 0,
                      "repetition_penalty": 1.1,
                      "pad_token_id": processor.tokenizer.eos_token_id}
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            out = model.generate(**inputs, **gen_kwargs)
        text = processor.tokenizer.decode(out[0][input_len:], skip_special_tokens=True)
        for pil in opened:
            if isinstance(pil, object) and hasattr(pil, "close"):
                pil.close()
        return text


register_adapter(
    "medgemma_mm",
    lambda logical_name, spec, env: MedGemmaMMAdapter(logical_name, spec, env),
)
