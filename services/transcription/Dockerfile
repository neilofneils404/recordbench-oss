# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b

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
COPY licenses ./licenses
COPY licenses /usr/share/licenses/recordbench-transcription/
COPY src ./src
COPY ui ./ui
COPY requirements-api*.lock /opt/transcription/
RUN pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/transcription/requirements-api-build.lock \
    && pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/transcription/requirements-api.lock \
    && pip install --no-cache-dir --no-deps --no-build-isolation . \
    && pip check
ENV HOME=/tmp/transcription-home

FROM base AS api
EXPOSE 8510
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=6 \
  CMD curl --fail --silent http://127.0.0.1:8510/health >/dev/null
CMD ["transcription-v2", "api"]

FROM base AS studio
EXPOSE 8511
CMD ["streamlit", "run", "ui/streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "8511", "--server.baseUrlPath", "transcript-studio", "--server.maxUploadSize", "5121"]

FROM base AS whisperx-builder
COPY compatibility ./compatibility
RUN python compatibility/build_whisperx.py --output /opt/transcription/wheels

FROM base AS worker
COPY --from=whisperx-builder /opt/transcription/wheels /opt/transcription/wheels
COPY requirements-worker.lock /opt/transcription/
RUN pip install --no-cache-dir --no-build-isolation --require-hashes --find-links=/opt/transcription/wheels -r /opt/transcription/requirements-worker.lock \
    && pip check
COPY requirements-nemotron*.lock /opt/transcription/
RUN python -m venv /opt/transcription/nemotron \
    && /opt/transcription/nemotron/bin/pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/transcription/requirements-nemotron-build.lock \
    && /opt/transcription/nemotron/bin/pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/transcription/requirements-nemotron.lock \
    && /opt/transcription/nemotron/bin/pip check
CMD ["transcription-v2", "worker"]
