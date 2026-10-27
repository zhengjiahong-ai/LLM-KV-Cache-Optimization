"""RC7: verify the extracted archive against its own file-level manifest.

This cannot prove the tree equals the tar.gz whose SHA-256 M1 published; it can only
prove the extracted tree is internally consistent and enumerate what identifiers are
available to link the two.

Reports:
  - file count and hash agreement against evidence-manifest.json
  - hash agreement against sha256-manifest.txt
  - which run identifiers are present
  - which tool / model / git identifiers the archive records
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10"
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "evidence-manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    ok = bad = missing = 0
    for item in files:
        target = ROOT / item["path"]
        if not target.exists():
            missing += 1
            continue
        if sha256_of(target) == item["sha256"]:
            ok += 1
        else:
            bad += 1

    print("== evidence-manifest.json verification ==")
    print(f"  entries            {len(files)}")
    print(f"  hash match         {ok}")
    print(f"  hash MISMATCH      {bad}")
    print(f"  file missing       {missing}")

    lines = (ROOT / "sha256-manifest.txt").read_text(encoding="utf-8").splitlines()
    parsed = [ln.split(maxsplit=1) for ln in lines if ln.strip()]
    m_ok = m_bad = 0
    for digest, rel in parsed:
        target = Path(rel)
        if not target.is_absolute():
            target = Path("local/continuum-native-cost-aware-bounded-v10-final-evidence") / rel
        if not target.exists():
            continue
        if sha256_of(target) == digest:
            m_ok += 1
        else:
            m_bad += 1
    print()
    print("== sha256-manifest.txt verification ==")
    print(f"  lines              {len(parsed)}")
    print(f"  resolvable+match   {m_ok}")
    print(f"  resolvable+DIFFER  {m_bad}")

    runs = sorted({p.parent.name for p in (ROOT / "runs").glob("*/run.json")})
    print()
    print("== run identifiers ==")
    print(f"  run directories with run.json  {len(runs)}")
    print(f"  first / last                   {runs[0]} / {runs[-1]}")

    summary = json.loads((ROOT / "execution-summary.json").read_text(encoding="utf-8"))
    print()
    print("== recorded identifiers (linkage candidates) ==")
    for key in sorted(summary):
        if any(t in key for t in ("sha", "git", "tool", "status", "count")):
            print(f"  {key:26s} {summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
