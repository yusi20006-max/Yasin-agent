#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Yasin-Agent Termux bootstrap. Termux/Android is a first-class target.

if [ "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]; then
  echo "ERROR: this installer must run inside Termux." >&2
  exit 1
fi

pkg update -y
pkg upgrade -y
pkg install -y python git clang make pkg-config openssl openssl-tool libffi cmake patchelf rust

PYTHON_BIN="${PREFIX}/bin/python"
"${PYTHON_BIN}" --version

rm -rf .venv
"${PYTHON_BIN}" -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[server]'
python -m pip install "pytest>=7.4,<10"

python - <<'PY'
import importlib.metadata as metadata
import sys
import agent_platform
from agent_platform.observability import get_system_info

sys_info = get_system_info()
print(f"Python: {sys.version}")
print(f"Yasin-Agent: {metadata.version('yasin-agent')}")
print(f"Platform: {sys_info['platform']} ({sys_info['arch']})")
print(f"Termux: {sys_info['is_termux']} | Android API: {sys_info['android_api_level']}")
print(f"Yasin-Agent import: OK ({agent_platform.__file__})")
PY

python -m pytest -q

# Standalone CLI smoke test. This does not require Yasin-Core or Yasin-AI.
python -m agent_platform.cli agent run news_bot

# Verify server entrypoint import
python -c "import agent_platform.server; print('Server entrypoint import OK')"

printf '%s\n' \
  'Yasin-Agent Termux installation completed successfully.' \
  'Activate: source .venv/bin/activate' \
  'CLI: python -m agent_platform.cli --help' \
  'Smoke: python -m agent_platform.cli agent run news_bot' \
  'Server: python -m agent_platform.server'
