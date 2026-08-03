# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- stage 2: runtime -------------------------------------------------------
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv libglib2.0-0 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# GPU wheels first, on the cu126 line for BOTH frameworks.
# Then install everything else, stripping the CPU-only torch/paddle lines.
RUN pip3 install --break-system-packages --no-cache-dir \
      torch==2.6.0+cu126 torchvision==0.21.0+cu126 torchaudio==2.6.0+cu126 \
      --index-url https://download.pytorch.org/whl/cu126 \
 && pip3 install --break-system-packages --no-cache-dir \
      paddlepaddle-gpu==3.3.1 \
      -i https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
 && grep -vE '^(torch|torchaudio|paddlepaddle)\b' requirements.txt > /tmp/req.txt \
 && pip3 install --break-system-packages --no-cache-dir -r /tmp/req.txt

# Model assets — baked in so the image is the whole deliverable.
COPY models/weights/                      /app/models/weights/
COPY .docker/hf-cache/                    /root/.cache/huggingface/
COPY .docker/paddlex/                     /root/.paddlex/

COPY --from=ui /frontend/dist             /app/frontend/dist
COPY core/    /app/core/
COPY models/  /app/models/
COPY stages/  /app/stages/
COPY server/  /app/server/
COPY config/  /app/config/
COPY data/    /app/data/

ENV SS_ENV=dev_4060 SS_HOST=0.0.0.0 SS_PORT=8000 SS_WARMUP=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
