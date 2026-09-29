# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM clamav/clamav:stable@sha256:594d54aff5ad3b1a5211d67cdc6d49a9a332276da35d821c3dd4cf6c4cdf6237
# Keep the upstream service contract while applying available distribution fixes.
RUN apk upgrade --no-cache
