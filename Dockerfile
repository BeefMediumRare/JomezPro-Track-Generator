FROM python:3.13-slim

# ffmpeg pulls frames out of the video; nodejs runs the extension's validateTrack
# as the conformance check; git clones the output repo and pushes tracks in server
# mode. libglib2.0-0 is what opencv-python-headless needs; curl/unzip fetch deno.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs git libglib2.0-0 curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp now needs a JavaScript runtime for reliable YouTube extraction. Without
# one it falls back to a degraded client whose downloads intermittently fail with
# HTTP 403. Deno is the runtime yt-dlp auto-detects on PATH.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && deno --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "generate.py"]
