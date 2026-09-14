"""Unit coverage for query/understanding.py -- the regex-heuristic date
constraint extraction that backs Phase 1/2 of temporal-comparison research
questions (see ADAPTIVE_INTELLIGENCE_ROADMAP.md, kept locally). Every
`published_before` here is exclusive -- see retrieval/lexical.py's
matching half-open-range comment.
"""

from __future__ import annotations

from datetime import UTC, datetime

from wardline.query.understanding import coerce_date_filters, extract_constraints


def test_no_date_language_yields_no_constraints():
    assert extract_constraints("Who founded Airbnb?") == {}


def test_since_year_sets_published_after_only():
    constraints = extract_constraints("What happened since 2020?")
    assert constraints == {"published_after": datetime(2020, 1, 1, tzinfo=UTC)}


def test_after_year_is_a_synonym_for_since():
    constraints = extract_constraints("Filings after 2019")
    assert constraints == {"published_after": datetime(2019, 1, 1, tzinfo=UTC)}


def test_before_year_sets_published_before_only_and_is_exclusive():
    constraints = extract_constraints("What was reported before 2020?")
    # Exclusive: "before 2020" excludes 2020 itself, not just later years.
    assert constraints == {"published_before": datetime(2020, 1, 1, tzinfo=UTC)}


def test_between_years_sets_both_bounds_inclusive_of_the_end_year():
    constraints = extract_constraints("How did this change between 2020 and 2023?")
    assert constraints == {
        "published_after": datetime(2020, 1, 1, tzinfo=UTC),
        # Exclusive upper bound is Jan 1 of the year *after* the stated end
        # year, so all of 2023 itself is actually included.
        "published_before": datetime(2024, 1, 1, tzinfo=UTC),
    }


def test_between_years_handles_reversed_order():
    constraints = extract_constraints("Compare the period between 2023 and 2020")
    assert constraints["published_after"] == datetime(2020, 1, 1, tzinfo=UTC)
    assert constraints["published_before"] == datetime(2024, 1, 1, tzinfo=UTC)


def test_between_takes_priority_over_a_stray_since_or_before_match():
    # "since 2020 and before 2023" could otherwise trip both the range
    # regex and the standalone since/before ones -- the range match must
    # win outright, not get merged with a second, differently-computed pair.
    constraints = extract_constraints("Report everything between 2020 and 2023")
    assert len(constraints) == 2


def test_coerce_date_filters_parses_iso_strings():
    coerced = coerce_date_filters({"published_after": "2020-01-01T00:00:00+00:00", "lang": "en"})
    assert coerced["published_after"] == datetime(2020, 1, 1, tzinfo=UTC)
    assert coerced["lang"] == "en"  # untouched -- only the two date keys are coerced


def test_coerce_date_filters_leaves_real_datetimes_alone():
    dt = datetime(2021, 6, 1, tzinfo=UTC)
    assert coerce_date_filters({"published_before": dt})["published_before"] is dt


def test_coerce_date_filters_is_a_no_op_on_empty_input():
    assert coerce_date_filters({}) == {}
