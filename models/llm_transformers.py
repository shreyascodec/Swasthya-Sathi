"""HF Transformers LLM adapter (Sarvam-1-2B, MedGemma-4B).

Loads with 4-bit (INT4) quantization via bitsandbytes to fit the 8 GB card.
Handles both instruct models (chat template) and base models like Sarvam-1
(few-shot: system+user concatenated). MedGemma is gated — set HF_TOKEN and accept
the license on Hugging Face first.

Setup (per phase, on the 4060):
    pip install torch transformers accelerate bitsandbytes
    # MedGemma: huggingface-cli login  (and accept the model license)
"""

from __future__ import annotations

from core.model_manager import register_adapter
from models.llm_base import LLMAdapterBase, LLMUnavailable


class TransformersAdapter(LLMAdapterBase):
    default_vram_mb = 2600

    def _build(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as exc:  # pragma: no cover - env dependent
            raise LLMUnavailable(
                "transformers/torch/bitsandbytes not installed. "
                "`pip install torch transformers accelerate bitsandbytes`, "
                "or swap llm to stub_llm."
            ) from exc

        # bfloat16 (not fp16): Gemma-family models produce NaN/degenerate logits
        # in float16. bf16 is supported on the RTX 4060 and safe for all candidates.
        compute_dtype = torch.bfloat16 if self.is_gpu else torch.float32

        quant_cfg = None
        if self.spec.get("quant", "int4").startswith("int4") and self.is_gpu:
            quant_cfg = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=compute_dtype,
            )

        tok = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            quantization_config=quant_cfg,
            device_map="auto" if self.is_gpu else None,
            dtype=compute_dtype,
        )
        model.eval()
        return {"tok": tok, "model": model, "torch": torch}

    def _generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        tok = self._handle["tok"]
        model = self._handle["model"]
        torch = self._handle["torch"]

        base_mode = False
        if self.is_instruct and tok.chat_template:
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user}]
            # return_dict keeps this working for multimodal chat models
            # (e.g. MedGemma/Gemma3) where the template yields a BatchEncoding.
            inputs = tok.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors="pt",
            ).to(model.device)
        elif self.is_instruct:
            # Instruct model without a chat template (e.g. Airavata): tulu format.
            prompt = f"<|user|>\n{system}\n\n{user}\n<|assistant|>\n"
            inputs = tok(prompt, return_tensors="pt").to(model.device)
        else:
            # Base model (e.g. Sarvam-1): one worked example — base models can't
            # follow instructions zero-shot; few-shot is the fair evaluation.
            from stages.summary_build import FEW_SHOT_EXAMPLE
            base_mode = True
            prompt = f"{system}\n\n{FEW_SHOT_EXAMPLE}\n\n{user}\n\nJSON:\n"
            inputs = tok(prompt, return_tensors="pt").to(model.device)

        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=max(temperature, 1e-5),
                pad_token_id=tok.eos_token_id,
            )
        text = tok.decode(out[0][input_len:], skip_special_tokens=True)
        if base_mode:
            text = _truncate_at_json(text)
        return text


def _truncate_at_json(text: str) -> str:
    """Cut a base model's completion at the first balanced JSON object.

    Base models keep generating after the answer (more examples, prose); the
    parser's first-{ .. last-} span would then swallow the garbage.
    """
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text


register_adapter("transformers_llm", lambda logical_name, spec, env: TransformersAdapter(logical_name, spec, env))
