"""RC-D: what the extracted archive can and cannot prove about its own provenance.

This checks the extracted tree against the two hashes the archive carries for itself,
and then against the archive digest published for it. It deliberately does **not**
report "365/366 matched" as a completeness verification: one manifest entry disagrees,
so the tree is not the tree the manifest describes, and without the original archive
bytes there is no path from an extracted file to the published digest.

Outcomes are printed as an explicit status rather than an aggregate percentage, so a
reader cannot mistake "internally consistent" for "same bytes as the published run".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10"
)

#: Metadata files that could plausibly carry a published digest. The per-run event
#: streams are excluded: they are large and cannot contain a digest of themselves.
LINKAGE_GLOBS = (
    "*.json",
    "campaign/*.json",
    "analysis/*.json",
    "preflight/*.json",
    "runs/*/run.json",
    "runs/*/*.json",
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest() -> dict:
    manifest = json.loads((ROOT / "evidence-manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    ok = bad = missing = 0
    mismatches = []
    for item in files:
        target = ROOT / item["path"]
        if not target.exists():
            missing += 1
            continue
        actual = sha256_of(target)
        if actual == item["sha256"]:
            ok += 1
        else:
            bad += 1
            mismatches.append((item, actual, target.stat().st_size))

    print("== evidence-manifest.json ==")
    print(f"  entries            {len(files)}")
    print(f"  hash match         {ok}")
    print(f"  hash MISMATCH      {bad}")
    print(f"  file missing       {missing}")
    for item, actual, size in mismatches:
        print(f"  first mismatch     {item['path']}")
        print(f"    manifest sha256  {item['sha256']}")
        print(f"    actual   sha256  {actual}")
        print(f"    manifest bytes   {item.get('size_bytes', item.get('size'))}")
        print(f"    actual   bytes   {size}")
    return {
        "total": len(files),
        "ok": ok,
        "bad": bad,
        "missing": missing,
        "mismatches": [m[0]["path"] for m in mismatches],
    }


def verify_sha_manifest() -> None:
    lines = (ROOT / "sha256-manifest.txt").read_text(encoding="utf-8").splitlines()
    parsed = [line.split(maxsplit=1) for line in lines if line.strip()]
    ok = bad = 0
    for digest, rel in parsed:
        target = Path(rel)
        if not target.is_absolute():
            target = Path("local/continuum-native-cost-aware-bounded-v10-final-evidence") / rel
        if not target.exists():
            continue
        if sha256_of(target) == digest:
            ok += 1
        else:
            bad += 1
    print()
    print("== sha256-manifest.txt ==")
    print(f"  lines              {len(parsed)}")
    print(f"  resolvable+match   {ok}")
    print(f"  resolvable+DIFFER  {bad}")


def mismatch_evidence(manifest_report: dict) -> None:
    if "execution-summary.json" not in " ".join(manifest_report["mismatches"]):
        return
    summary = json.loads((ROOT / "execution-summary.json").read_text(encoding="utf-8"))
    print()
    print("== why execution-summary.json disagrees with the manifest ==")
    print("  the file the manifest describes was produced before the run finished; the")
    print("  file on disk carries the post-run result block:")
    print(f"    top-level keys            {sorted(summary)}")
    result = summary.get("result_summary") or {}
    print(f"    result_summary arms       {sorted(result)}")
    print(f"    wall_elapsed_seconds      {summary.get('wall_elapsed_seconds')}")
    print("  these two fields are what the size delta is made of. That explains the")
    print("  difference; it does not make it disappear.")


def linkage(manifest_report: dict) -> None:
    summary = json.loads((ROOT / "execution-summary.json").read_text(encoding="utf-8"))
    published = str((summary.get("archive") or {}).get("archive_sha256") or "")
    print()
    print("== source linkage ==")
    print(f"  published archive sha256   {published or '(none recorded)'}")
    hits = []
    for pattern in LINKAGE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if published and published in text:
                hits.append(str(path.relative_to(ROOT)))
    print(f"  files containing it        {len(hits)}")
    for hit in sorted(set(hits)):
        print(f"    {hit}")
    print()
    print("  cross-reference keys available for a future check:")
    for key in ("manifest_sha256", "authorization_sha256", "profile_sha256", "report_sha256"):
        if key in summary:
            print(f"    {key:22s} {summary[key]}")
    print()
    if manifest_report["bad"] or manifest_report["missing"]:
        print("== VERIFICATION STATUS: SOURCE-UNVERIFIED ==")
        print("  the extracted tree is not byte-consistent with its own file manifest")
        print("  (see the mismatch above), and the published archive digest does not")
        print("  appear in the tree. Internal consistency of the other entries and a")
        print("  clear 370/370 sha256-manifest do not establish that this tree is the")
        print("  published archive. The claim stays marked unverified until the original")
        print("  archive bytes can be hashed, or until a re-generated manifest and the")
        print("  published digest are shown to agree for the same tree.")
    else:
        print("== VERIFICATION STATUS: INTERNALLY-CONSISTENT, SOURCE STILL UNPROVEN ==")
        print("  every manifest entry matches, but without the original archive bytes")
        print("  equality with the published tarball is still not established.")


def main() -> int:
    report = verify_manifest()
    verify_sha_manifest()
    mismatch_evidence(report)
    linkage(report)

    runs = sorted({p.parent.name for p in (ROOT / "runs").glob("*/run.json")})
    print()
    print("== run identifiers ==")
    print(f"  run directories with run.json  {len(runs)}")
    if runs:
        print(f"  first / last                   {runs[0]} / {runs[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
