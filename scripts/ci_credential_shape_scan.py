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
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                if (
                    name == "credentialed_postgres_url"
                    and match.group(0).startswith("postgresql://USER:PASSWORD@")
                ):
                    # Documentation may contain an intentionally non-secret
                    # placeholder connection string. Keep scanning every file,
                    # including this scanner itself, but do not treat the
                    # explicit placeholder tuple as a credential.
                    continue
                findings.append((relative, name))
                break

    if findings:
        for relative, name in findings:
            print(f"credential-shape finding: {relative}: {name}")
        return 2
    print(f"credential_shape_scan=PASS tracked_files={len(tracked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
