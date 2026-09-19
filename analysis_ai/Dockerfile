FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-service.txt ./
RUN pip install --no-cache-dir -r requirements-service.txt

# Same approach and pins as the notes app's worker image: faster-whisper needs
# cuBLAS/cuDNN, supplied as pip wheels and pointed at directly.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib

COPY analysis_ai ./analysis_ai
COPY scripts ./scripts
COPY web ./web

# AAI_IN_CONTAINER makes transcription run Whisper directly (there is no docker
# inside this container). Data lives on a bind mount so it survives rebuilds.
ENV AAI_IN_CONTAINER=1 AAI_DATA_DIR=/data
EXPOSE 8090
CMD ["python", "-m", "analysis_ai", "serve", "--host", "0.0.0.0", "--port", "8090"]
