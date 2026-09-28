"""Catch known project typos without relying on a platform dictionary or downloads."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPOS = json.loads((ROOT / "spelling.json").read_text(encoding="utf-8"))["typos"]
SCAN = [ROOT / name for name in ("README.md", "SECURITY.md", "CONTRIBUTING.md", "SUPPORT.md", "GOVERNANCE.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md")]
SCAN += sorted((ROOT / "docs").glob("*.md"))
errors = []
for path in SCAN:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for match in re.finditer(r"\b[a-zA-Z]+\b", line):
            word = match.group().lower()
            if word in TYPOS:
                errors.append(f"{path.relative_to(ROOT)}:{number}: {match.group()} -> {TYPOS[word]}")
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"Checked {len(SCAN)} documentation files against {len(TYPOS)} known typos")
