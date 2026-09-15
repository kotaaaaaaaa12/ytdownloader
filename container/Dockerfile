FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.deno/bin:${PATH}" \
    BGUTIL_HOME="/opt/bgutil-ytdlp-pot-provider/server"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg curl ca-certificates unzip git chromium \
       build-essential pkg-config libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PO Token provider. Keep the server source in a fixed location and use its
# script provider from yt-dlp. Deno handles BotGuard/PO token generation.
RUN git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && deno install --allow-scripts=npm:canvas --frozen

COPY app.py .

RUN mkdir -p /data/jobs
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
