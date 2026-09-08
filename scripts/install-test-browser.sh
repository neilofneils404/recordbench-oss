#!/usr/bin/env bash
# Install only the reviewed browser pair into a new contributor-owned directory.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo 'Usage: scripts/install-test-browser.sh NEW_DIRECTORY' >&2
  exit 2
fi
browser_dir="$1"
mkdir -- "$browser_dir"
cd -- "$browser_dir"
for archive in chrome-linux64.zip chromedriver-linux64.zip; do
  curl --fail --silent --show-error --location --retry 2 --max-time 180 \
    "https://storage.googleapis.com/chrome-for-testing-public/152.0.7977.82/linux64/$archive" \
    --output "$archive"
done
sha256sum --check <<'SUMS'
0704631fb3e4f741092e08f55272f90abc3e307f991f05f332924364415b02e0  chrome-linux64.zip
dd7dfa6a9cb0580a3bf0a03e4b58806a8c70303e2963fff36be6190a7abb4f3c  chromedriver-linux64.zip
SUMS
unzip -q chrome-linux64.zip
unzip -q chromedriver-linux64.zip
./chrome-linux64/chrome --version
./chromedriver-linux64/chromedriver --version
