# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.11-slim-bookworm

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/transcription/venv/bin:$PATH
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/transcription/app
RUN python -m venv /opt/transcription/venv
COPY pyproject.toml README.md ./
COPY src ./src
COPY ui ./ui
RUN pip install --no-cache-dir .
ENV HOME=/tmp/transcription-home

FROM base AS api
EXPOSE 8510
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=6 \
  CMD curl --fail --silent http://127.0.0.1:8510/health >/dev/null
CMD ["transcription-v2", "api"]

FROM base AS studio
EXPOSE 8511
CMD ["streamlit", "run", "ui/streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "8511", "--server.baseUrlPath", "transcript-studio", "--server.maxUploadSize", "5121"]

FROM base AS worker
RUN pip install --no-cache-dir '.[ml]'
CMD ["transcription-v2", "worker"]
