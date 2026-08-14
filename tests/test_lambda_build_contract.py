from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_lambda_dependency_is_exactly_pinned():
    assert (ROOT / "requirements-lambda.txt").read_text(encoding="utf-8").strip() == (
        "psycopg[binary]==3.3.4"
    )


def test_lambda_build_fails_before_dependency_install_without_explicit_ca(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_lambda_package.py"),
            "--output",
            str(tmp_path / "lambda.zip"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": str(Path(sys.executable).parent)},
    )
    assert result.returncode != 0
    assert "CA input is required" in result.stderr
    assert not (tmp_path / "lambda.zip").exists()


def test_lambda_build_does_not_depend_on_ignored_venv_ca_path():
    source = (ROOT / "scripts" / "build_lambda_package.py").read_text(
        encoding="utf-8"
    )
    assert '.venv" / "cockroach-cloud-root.crt' not in source
    assert "COCKROACH_CA_FILE" in source
