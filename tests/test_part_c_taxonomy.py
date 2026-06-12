"""Part C Stage 1: generated taxonomy acceptance."""

from config.gap_taxonomy import (
    ALL_CATEGORIES,
    CORE_CATEGORIES,
    GAP_CATEGORIES,
    GAP_SEARCH_TEMPLATES,
    LONG_TAIL,
    QUERY_TEMPLATES,
    queries_for_category,
    synonyms_for,
)


def test_long_tail_size():
    assert len(LONG_TAIL) >= 140          # acceptance: >= 140 categories


def test_every_category_has_templates_and_core_has_synonyms():
    assert len(QUERY_TEMPLATES) >= 2
    for cat in CORE_CATEGORIES:
        qs = queries_for_category(cat, "Lexington")
        assert len(qs) >= 2 and all("Lexington" in q for q in qs)
        assert synonyms_for(cat), f"core category {cat} needs >=1 parent synonym"


def test_query_variants_differ():
    qs = queries_for_category("pottery", "Arlington")
    assert len(set(qs)) == len(qs) == 3
    assert "pottery" in qs[0]


def test_backward_compat_shape():
    # old API: tuple of slugs + str templates with {town}
    assert isinstance(GAP_CATEGORIES, tuple) and len(GAP_CATEGORIES) >= 150
    for cat in ("soccer", "stem", "preschool"):
        assert "{town}" in GAP_SEARCH_TEMPLATES[cat]


def test_display_names_resolve():
    assert ALL_CATEGORIES["stem"] == "STEM"
    assert ALL_CATEGORIES["ninja_warrior"] == "ninja warrior"
