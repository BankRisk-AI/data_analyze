import math

import pytest

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.domain import RULES, column_role
from app.modules.eba_processing.domain.binning import clip_bounds, make_edges, transform_bounds
from app.modules.eba_processing.domain import parse_dims


def test_linear_edges_are_equally_spaced():
    e = make_edges(0, 10, 5)
    assert e == [0, 2, 4, 6, 8, 10] and len(e) == 6


def test_log_edges_have_equal_ratios():
    e = make_edges(1, 1000, 3, "log")
    assert [round(x, 6) for x in e] == [1, 10, 100, 1000]
    assert math.isclose(e[2] / e[1], e[1] / e[0])


def test_degenerate_and_invalid_ranges():
    assert make_edges(5, 5, 10) == [5, 5]
    with pytest.raises(InvalidParameter): make_edges(0, 10, 0)
    with pytest.raises(InvalidParameter): make_edges(10, 0, 5)
    with pytest.raises(InvalidParameter, match="positive"): make_edges(-1, 10, 5, "log")
    assert transform_bounds(10, 1000, "log") == (1.0, 3.0) and transform_bounds(10, 1000, "linear") == (10, 1000)


def test_clip_bounds():
    assert clip_bounds("none", 0, 100, 1, 25, 75, 99)[:2] == (0, 100)
    lo, hi, note = clip_bounds("p01-p99", 0, 100, 1, 25, 75, 99)
    assert (lo, hi) == (1, 99) and "percentiles" in note
    lo, hi, _ = clip_bounds("iqr", 0, 100, 1, 25, 75, 99)
    assert (lo, hi) == (0, 100)                      # fences at -50 and 150 are limited to the data range
    lo, hi, _ = clip_bounds("iqr", -1000, 1000, 1, 25, 35, 99)
    assert (lo, hi) == (10, 50)


def test_column_roles():
    assert [column_role(c) for c in ["lei_code", "nsa", "period", "item", "label", "amount", "footnote", "perf_status"]] == ["key", "key", "key", "key", "label", "measure", "annotation", "dimension"]


def test_parse_dims():
    assert parse_dims(["portfolio:1", "status:a:b"]) == {"portfolio": "1", "status": "a:b"}
    assert parse_dims(None) == {}
    with pytest.raises(InvalidParameter): parse_dims(["oops"])
    with pytest.raises(InvalidParameter): parse_dims([":x"])


def test_rule_catalogue_is_consistent():
    ids = [r.id for r in RULES]
    assert ids == [f"V{i:02d}" for i in range(1, 14)] and len(set(ids)) == 13
    assert {r.severity for r in RULES} == {"error", "warning", "info"}
