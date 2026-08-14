from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "decisionvault-lambda.zip",
    )
    parser.add_argument(
        "--vendor-source",
        type=Path,
        help=(
            "Reuse an existing Lambda vendor directory instead of downloading "
            "requirements again. The current DecisionVault source is always "
            "re-copied after the vendor tree."
        ),
    )
    args = parser.parse_args()

    build_dir = ROOT / ".venv" / "lambda-package"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if args.vendor_source:
        vendor_source = args.vendor_source.resolve()
        if not vendor_source.is_dir():
            raise SystemExit(f"vendor source does not exist: {vendor_source}")
        shutil.copytree(vendor_source, build_dir)
        packaged_source = build_dir / "decisionvault"
        if packaged_source.exists():
            shutil.rmtree(packaged_source)
        packaged_handler = build_dir / "lambda_function.py"
        if packaged_handler.exists():
            packaged_handler.unlink()
    else:
        build_dir.mkdir(parents=True)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--target",
                str(build_dir),
                "-r",
                str(ROOT / "requirements-lambda.txt"),
            ],
            check=True,
        )
    shutil.copytree(ROOT / "src" / "decisionvault", build_dir / "decisionvault")
    cloud_ca = ROOT / ".venv" / "cockroach-cloud-root.crt"
    if cloud_ca.exists():
        shutil.copy2(cloud_ca, build_dir / "cockroach-cloud-root.crt")
    (build_dir / "lambda_function.py").write_text(
        "from decisionvault.aws_lambda import lambda_handler\n",
        encoding="utf-8",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(build_dir.rglob("*")):
            relative = path.relative_to(build_dir)
            if not path.is_file():
                continue
            if "__pycache__" in relative.parts or path.suffix == ".pyc":
                continue
            if relative.name == ".lock":
                continue
            archive.write(path, relative)
    print(f"lambda_package={args.output}")
    print(f"lambda_package_bytes={args.output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
