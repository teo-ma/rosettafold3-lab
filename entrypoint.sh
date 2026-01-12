#!/usr/bin/env bash
set -euo pipefail

CKPT_PATH="${RF3_CKPT_PATH:-/models/rf3.ckpt}"
CKPT_URL="${RF3_CKPT_URL:-http://files.ipd.uw.edu/pub/rf3/rf3_foundry_01_24_latest.ckpt}"

mkdir -p "$(dirname "$CKPT_PATH")"

if [[ -f "$CKPT_PATH" ]]; then
  echo "[rf3-demo] checkpoint found: $CKPT_PATH"
else
  echo "[rf3-demo] checkpoint not found; starting background download: $CKPT_URL"
  (
    set -euo pipefail
    tmp="${CKPT_PATH}.tmp"
    rm -f "$tmp"
    wget -O "$tmp" "$CKPT_URL"
    mv "$tmp" "$CKPT_PATH"
    echo "[rf3-demo] checkpoint download complete: $CKPT_PATH"
  ) &
fi

exec python -m rf3_demo
