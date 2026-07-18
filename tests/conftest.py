"""Hermetic test setup — no keys, no network, no repo writes."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import dotenv  # noqa: E402

dotenv.load_dotenv = lambda *a, **k: None
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["BASELINE_HRS_PER_SPEC"] = "6"

import pytest  # noqa: E402

from app import deliverables, main, receipt  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt, "LOG", tmp_path / "receipts.jsonl")
    monkeypatch.setattr(deliverables, "OUT", tmp_path / "deliverables")
    monkeypatch.setattr(main, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(main, "DATA", tmp_path / "data")
    monkeypatch.setattr(main, "_SPECS", {})
    return tmp_path


@pytest.fixture
def extraction():
    """Factory for a clean merged extraction."""
    def _make(**over):
        d = {"coat_systems": [{"surface": "tank exterior", "prep_standard": "SSPC-SP10",
                               "coats": [{"product_or_type": "zinc primer",
                                          "dft_min_mils": 3.0, "dft_max_mils": 5.0}],
                               "notes": "", "page": "p.12", "flag": False}],
             "environmental_limits": [{"condition": "relative humidity", "limit": "max 85%",
                                       "page": "p.13", "flag": False}],
             "hold_points": [{"point": "prep sign-off before primer", "page": "p.14", "flag": False}],
             "needs_review": [], "guard_violations": 0}
        d.update(over)
        return d
    return _make
