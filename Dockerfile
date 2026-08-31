# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS application

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/recordbench/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        imagemagick \
        libnss-sss \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/recordbench/app
RUN python -m venv /opt/recordbench/venv
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres]'

ENV HOME=/tmp/recordbench-home
EXPOSE 8786
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=6 \
  CMD python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8786/health',timeout=3)); assert p['status'] in {'ok','degraded'} and p['storage']['status']=='ready'"

CMD ["python", "-m", "case_intelligence.workbench", "--host", "0.0.0.0", "--port", "8786", "--runtime", "/var/lib/recordbench/runtime"]

FROM application AS retrieval
RUN pip install --no-cache-dir '.[models]'
EXPOSE 8787
HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=18 \
  CMD python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=3)); assert p['status']=='ok' and p['embedding_loaded'] and p['reranker_loaded']"
CMD ["python", "-m", "case_intelligence.retrieval_worker", "--host", "0.0.0.0", "--port", "8787"]
