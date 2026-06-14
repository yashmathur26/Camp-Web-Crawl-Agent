"""Curated colleges/universities per town (hybrid discovery — Thread 2).

This is the RELIABLE half of college discovery: a small, verifiable list of
degree-granting institutions per town, used to (a) seed high-priority
"{college} summer youth camp" queries in Phase A and (b) raise the town's search
budget (each college is its own provider surface). The other half — dynamic
`.edu` discovery in src/run.py — covers towns/colleges not listed here, so this
table never has to be exhaustive and is NOT a hard-coded allowlist.

Hosts are the institution's primary domain (no www). Verified entries only.
"""

from __future__ import annotations

COLLEGES_BY_TOWN: dict[str, list[dict]] = {
    "Waltham": [
        {"name": "Bentley University", "host": "bentley.edu"},
        {"name": "Brandeis University", "host": "brandeis.edu"},
    ],
    "Cambridge": [
        {"name": "Harvard University", "host": "harvard.edu"},
        {"name": "Massachusetts Institute of Technology", "host": "mit.edu"},
        {"name": "Lesley University", "host": "lesley.edu"},
    ],
    "Newton": [
        {"name": "Boston College", "host": "bc.edu"},
        {"name": "Lasell University", "host": "lasell.edu"},
    ],
    "Medford": [
        {"name": "Tufts University", "host": "tufts.edu"},
    ],
    "Framingham": [
        {"name": "Framingham State University", "host": "framingham.edu"},
    ],
    "Lowell": [
        {"name": "University of Massachusetts Lowell", "host": "uml.edu"},
    ],
    "Boston": [
        {"name": "Boston University", "host": "bu.edu"},
        {"name": "Northeastern University", "host": "northeastern.edu"},
        {"name": "Suffolk University", "host": "suffolk.edu"},
        {"name": "Emerson College", "host": "emerson.edu"},
        {"name": "Berklee College of Music", "host": "berklee.edu"},
        {"name": "University of Massachusetts Boston", "host": "umb.edu"},
        {"name": "Wentworth Institute of Technology", "host": "wit.edu"},
        {"name": "Simmons University", "host": "simmons.edu"},
    ],
    "Worcester": [
        {"name": "Worcester Polytechnic Institute", "host": "wpi.edu"},
        {"name": "Clark University", "host": "clarku.edu"},
        {"name": "College of the Holy Cross", "host": "holycross.edu"},
    ],
}


def colleges_for(town: str) -> list[dict]:
    """Curated colleges for a town (empty if none listed; dynamic .edu discovery
    fills the gap at run time)."""
    return COLLEGES_BY_TOWN.get(town, [])
