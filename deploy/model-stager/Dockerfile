FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
RUN apt-get update \
    && apt-get install -y --no-install-recommends libssl3 openssl \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements*.lock /opt/stager/
RUN python -m pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/stager/requirements-build.lock \
    && python -m pip install --no-cache-dir --no-build-isolation --require-hashes -r /opt/stager/requirements.lock \
    && python -m pip check
WORKDIR /workspace
ENTRYPOINT ["python", "scripts/stage-models.py"]
