#!/usr/bin/env bash
# Runner-only setup. Avoid downloading 100+ desktop/media packages from slow apt mirrors.
set -euo pipefail

mode="${1:?usage: bash cloud/setup.sh render|audio}"
if [[ "$mode" != render && "$mode" != audio ]]; then
  echo "Unknown setup mode" >&2
  exit 1
fi

python -m pip install --disable-pip-version-check --timeout 30 --retries 3 -r cloud/requirements.txt

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  # A static GPL build includes libx264, ffprobe and the audio filters used by mix.py.
  # Check the release's published digest before executing the downloaded binaries.
  directory="$RUNNER_TEMP/aitrends-ffmpeg"
  archive="ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz"
  base="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
  mkdir -p "$directory"
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
    "$base/$archive" --output "$directory/$archive"
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 60 \
    "$base/checksums.sha256" --output "$directory/checksums.sha256"
  (
    cd "$directory"
    awk -v name="$archive" '$2 == name || $2 == "*" name { print }' checksums.sha256 | sha256sum --check --status
    tar -xJf "$archive" --strip-components=1
  )
  export PATH="$directory/bin:$PATH"
  echo "$directory/bin" >> "$GITHUB_PATH"
fi
ffmpeg -version
ffprobe -version

if [[ "$mode" == render ]]; then
  npm ci --no-audit --no-fund
  # ubuntu-24.04 already has the Chromium runtime libraries. Bundled webfonts supply
  # the studio typefaces, so an unconditional apt upgrade/font installation is unnecessary.
  npx playwright install --only-shell chromium
  check_browser() {
    node --input-type=module -e 'import { chromium } from "playwright"; const b = await chromium.launch({args:["--use-angle=swiftshader","--enable-unsafe-swiftshader","--disable-dev-shm-usage"]}); await b.close();'
  }
  if ! check_browser; then
    # Bounded fallback if a future runner image removes a necessary shared library.
    timeout 180s npx playwright install-deps chromium
    check_browser
  fi
fi
