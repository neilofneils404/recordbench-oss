# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM pgvector/pgvector:pg17@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f
# Keep the upstream service contract while applying available distribution fixes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libssl3 openssl libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*
