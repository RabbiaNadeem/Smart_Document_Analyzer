"""Tests for DocumentAnalyzer (requires en_core_web_sm)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.services.document_analyzer import DocumentAnalyzer


SAMPLE = """
Dr. Alice Chen is the lead engineer at Acme Robotics in Seattle.
She traveled to London last quarter to meet partners at Global Tech Ltd.
The team discussed supply chain improvements and hiring in New York.
Microsoft and Acme Robotics may collaborate on a warehouse automation pilot.
""".strip()


def test_summary_non_empty_and_coherent():
    a = DocumentAnalyzer(SAMPLE)
    s = a.summary()
    assert isinstance(s, str)
    assert len(s) > 40
    # Extractive summary should pull from the document vocabulary.
    lowered = s.lower()
    assert "alice" in lowered or "acme" in lowered or "seattle" in lowered


def test_key_points_list_of_strings():
    a = DocumentAnalyzer(SAMPLE)
    kp = a.key_points()
    assert isinstance(kp, list)
    assert 1 <= len(kp) <= 6
    for item in kp:
        assert isinstance(item, str)
        assert len(item) > 10


def test_entities_structure_and_content():
    a = DocumentAnalyzer(SAMPLE)
    ent = a.entities()
    assert set(ent.keys()) == {"people", "organizations", "locations"}
    assert isinstance(ent["people"], list)
    assert isinstance(ent["organizations"], list)
    assert isinstance(ent["locations"], list)

    people_l = [p.lower() for p in ent["people"]]
    orgs_l = [o.lower() for o in ent["organizations"]]
    locs_l = [loc.lower() for loc in ent["locations"]]

    assert any("alice" in p for p in people_l)
    assert any("acme" in o or "microsoft" in o or "global" in o for o in orgs_l)
    assert any("seattle" in loc or "london" in loc or "new york" in loc for loc in locs_l)


def test_empty_text():
    a = DocumentAnalyzer("")
    assert "no extractable text" in a.summary().lower()
    assert a.key_points() == []
    assert a.entities() == {"people": [], "organizations": [], "locations": []}


def test_whitespace_only():
    a = DocumentAnalyzer("   \n\t  ")
    assert "no extractable text" in a.summary().lower()


def test_summary_length_bounded():
    """Résumé-style blobs must not echo thousands of characters."""
    wall = (
        "JANE DOE | jane@example.com | +1-555-0100 | https://linkedin.com/in/janedoe\n\n"
        "PROFESSIONAL SUMMARY\n"
        "Senior software engineer with ten years building distributed systems and APIs. "
        "Led teams of eight across three time zones. Deep experience with Python, Go, "
        "and cloud infrastructure on AWS.\n\n"
        "EXPERIENCE\n"
        "Acme Corp — Staff Engineer (2020–present). Owned the payments platform migration. "
        "Reduced p99 latency by forty percent. "
        "Beta LLC — Engineer (2015–2020). Shipped the first mobile analytics pipeline.\n"
    )
    a = DocumentAnalyzer(wall)
    s = a.summary()
    assert len(s) <= 500
    assert "@" not in s
    assert "linkedin.com" not in s.casefold()
    assert "555" not in s or "engineer" in s.casefold()


def test_key_points_not_identical_to_summary():
    a = DocumentAnalyzer(SAMPLE)
    summ = a.summary()
    kps = a.key_points()
    assert kps
    for kp in kps:
        assert kp.casefold() != summ.casefold()
