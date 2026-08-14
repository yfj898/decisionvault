from __future__ import annotations

from pathlib import Path
import re
import subprocess


PATTERNS = {
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "cockroach_service_key": re.compile(r"\bCCDB1_[A-Za-z0-9_\-]+"),
    "credentialed_postgres_url": re.compile(
        r"postgres(?:ql)?://[^\s:@/]+:[^<\s@]+@"
    ),
}


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    findings: list[tuple[str, str]] = []
    for relative in tracked:
        path = Path(relative)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if relative == ".env.example":
            text = text.replace(
                "postgresql://USER:PASSWORD@HOST:26257/defaultdb?sslmode=verify-full",
                "",
            )
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append((relative, name))

    if findings:
        for relative, name in findings:
            print(f"credential-shape finding: {relative}: {name}")
        return 2
    print(f"credential_shape_scan=PASS tracked_files={len(tracked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
