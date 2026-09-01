"""Pasted LLM citation markers must not ship in source."""
import pathlib as pl

MARKERS = ("contentReference", "oaicite")


def test_common_sf_data_retrieval_is_clean():
    text = pl.Path("src/assist/common/sf_data_retrieval.py").read_text(encoding="utf-8")
    for marker in MARKERS:
        assert marker not in text, f"{marker} still present"


def test_no_citation_markers_anywhere_under_src():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(m in text for m in MARKERS):
            offenders.append(str(path))
    assert offenders == [], f"citation markers in {offenders}"
