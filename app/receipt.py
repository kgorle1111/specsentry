"""Value receipt per spec: pages, requirements, flags, estimator-hours displaced.

kn: the hours-displaced constant is the product spec's expected 4-8 hr manual
baseline scaled by extraction share; the pilot replaces it with the
contractor's own measured number in week one.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "receipts.jsonl"

BASELINE_HRS_PER_SPEC = float(os.getenv("BASELINE_HRS_PER_SPEC", "6"))


def log_spec(job, pages, sections, coat_systems, env_limits, hold_points, flags, guard_violations,
             outcome="spec_processed"):
    row = {"ts": datetime.now(timezone.utc).isoformat(), "job": job, "outcome": outcome,
           "pages": pages, "sections": sections, "coat_systems": coat_systems,
           "environmental_limits": env_limits, "hold_points": hold_points,
           "review_flags": flags, "guard_violations": guard_violations,
           "baseline_hrs": BASELINE_HRS_PER_SPEC}
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def rollup(path=None):
    """LOG resolved at call time so tests that repoint receipt.LOG see the right file."""
    path = Path(path or LOG)
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    specs = [r for r in rows if r["outcome"] == "spec_processed"]
    return {
        "specs_processed": len(specs),
        "pages_read": sum(r["pages"] for r in specs),
        "requirements_extracted": sum(r["coat_systems"] + r["environmental_limits"] + r["hold_points"]
                                      for r in specs),
        "review_flags_raised": sum(r["review_flags"] for r in specs),
        "price_guard_catches": sum(r["guard_violations"] for r in specs),
        "estimator_hours_baseline": round(sum(r["baseline_hrs"] for r in specs), 1),
    }


if __name__ == "__main__":
    import tempfile
    LOG = Path(tempfile.mkstemp(suffix=".jsonl")[1])
    log_spec("J1", pages=120, sections=9, coat_systems=4, env_limits=3, hold_points=5,
             flags=2, guard_violations=1)
    r = rollup(LOG)
    assert r["specs_processed"] == 1 and r["requirements_extracted"] == 12
    assert r["price_guard_catches"] == 1 and r["estimator_hours_baseline"] == 6
    print("receipt OK", r)
