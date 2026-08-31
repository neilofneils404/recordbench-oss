FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m pip install --no-cache-dir 'huggingface-hub>=0.34,<1' 'nltk>=3.9,<4'
WORKDIR /workspace
ENTRYPOINT ["python", "scripts/stage-models.py"]
