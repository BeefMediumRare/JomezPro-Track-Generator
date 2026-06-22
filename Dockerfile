FROM python:3.13-slim

# ffmpeg pulls frames out of the video; nodejs runs the extension's validateTrack
# as the conformance check; git clones the output repo and pushes tracks in server
# mode. libglib2.0-0 is what opencv-python-headless needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs git libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "generate.py"]
