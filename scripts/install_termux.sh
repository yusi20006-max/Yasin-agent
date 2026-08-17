#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Yasin-Agent Termux bootstrap. Termux/Android is a first-class target.

if [ "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]; then
  echo "ERROR: this installer must run inside Termux." >&2
  exit 1
fi

pkg update -y
pkg upgrade -y
pkg install -y python git clang make pkg-config openssl openssl-tool libffi cmake patchelf

PYTHON_BIN="${PREFIX}/bin/python"
"${PYTHON_BIN}" --version

rm -rf .venv
"${PYTHON_BIN}" -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python -m pip install "pytest>=7.4,<10"

python - <<'PY'
import importlib.metadata as metadata
import sys
import agent_platform

print(f"Python: {sys.version}")
print(f"Yasin-Agent: {metadata.version('yasin-agent')}")
print(f"Yasin-Agent import: OK ({agent_platform.__file__})")
PY

python -m pytest -q

# Standalone CLI smoke test. This does not require Yasin-Core or Yasin-AI.
python -m agent_platform.cli agent run news_bot

printf '%s\n' \
  'Yasin-Agent Termux installation completed successfully.' \
  'Activate: source .venv/bin/activate' \
  'CLI: python -m agent_platform.cli --help' \
  'Smoke: python -m agent_platform.cli agent run news_bot'
