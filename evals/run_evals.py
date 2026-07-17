"""Behavioral evals for the spec extractor — LIVE model vs the production prompt.
Golden set: hand-labeled spec excerpts in cases.json; graders are deterministic
(field equality, forbidden content, citation presence). Needs ANTHROPIC_API_KEY;
~$0.10/run. Grow cases.json from the pilot contractor's real specs.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import extract  # noqa: E402

RESULTS = Path(__file__).parent / "results"
CASES = json.loads((Path(__file__).parent / "cases.json").read_text())


def grade(case, d):
    fails = []
    joined = json.dumps(d)
    for want in case.get("expect_contains", []):
        if want.lower() not in joined.lower():
            fails.append(f"missing '{want}'")
    if case.get("expect_dft"):
        got = [(c.get("dft_min_mils"), c.get("dft_max_mils"))
               for cs in d["coat_systems"] for c in cs["coats"]]
        for pair in case["expect_dft"]:
            if tuple(pair) not in got:
                fails.append(f"missing DFT {pair}, got {got}")
    if case.get("forbid_regex"):
        clean = re.sub(r"\[REDACTED[^\]]*\]", "", joined)
        if re.search(case["forbid_regex"], clean, re.IGNORECASE):
            fails.append(f"forbidden content: {case['forbid_regex']}")
    if case.get("expect_min_flags") and len(d["needs_review"]) < case["expect_min_flags"]:
        fails.append(f"expected >= {case['expect_min_flags']} flags, got {len(d['needs_review'])}")
    if case.get("expect_citation") and not any(
            cs.get("page") for cs in d["coat_systems"]):
        fails.append("no page citations on coat systems")
    return fails


def run():
    rows, passed = [], 0
    for case in CASES:
        d = extract.extract_section(case["text"])
        fails = grade(case, d)
        passed += not fails
        rows.append({"case": case["name"], "pass": not fails, "fails": fails, "out": d})
        print(f"[{'PASS' if not fails else 'FAIL'}] {case['name']}" + (f" — {fails}" if fails else ""))
    print(f"\n{passed}/{len(CASES)} passed")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"passed": passed, "total": len(CASES), "rows": rows}, indent=2, default=str))
    print(f"results -> {out}")
    return passed == len(CASES)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
