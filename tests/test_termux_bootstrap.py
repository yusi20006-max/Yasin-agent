from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_termux.sh"


def test_termux_bootstrap_exists_and_is_fail_fast() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "pkg install -y python git clang make pkg-config openssl openssl-tool libffi cmake patchelf" in text
    assert '"${PYTHON_BIN}" -m venv .venv' in text
    assert "python -m pip install -e ." in text
    assert "python -m pytest -q" in text
    assert "python -m agent_platform.cli agent run news_bot" in text


def test_termux_bootstrap_uses_current_termux_python() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'PYTHON_BIN="${PREFIX}/bin/python"' in text
    assert '"${PYTHON_BIN}" --version' in text
