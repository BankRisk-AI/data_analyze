import math

import pytest

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.application import analytics as A
from app.modules.eba_processing.domain import Filters
from helpers import banks, lei, stage

AGG = ["XXXXXXXXXXXXXXXXXXXX,OT,202003,I1,Item one,0,5,", "XXXXXXXXXXXXXXXXXXXX,OT,202006,I1,Item one,0,5,"]


def hist(db, fid, **k):
    kw = dict(bins=k.pop("bins", 10), scale=k.pop("scale", "linear"), clip=k.pop("clip", "none"))
    return A.histogram(fid, db.schema, Filters(item=k.pop("item", "I1"), period=k.pop("period", "202003"), exclude_aggregate=True, **k), **kw)


# ------------------------------------------------------------------------------------------------ profile
def test_profile_counts_nulls_blanks_and_distincts_exactly(db):
    rows = ["A0000000000000000001,DE,202003,I1,x,0,1,", "A0000000000000000002,DE,202003,I1,x,,2,note", "A0000000000000000003,FR,202003,I2,x,   ,abc,", "A0000000000000000004,FR,202003,I2,x,1,,", "A0000000000000000005,FR,202006,I2,,1,5,"]
    _, fid = stage(db, rows)
    p = A.profile(fid, db.schema, Filters())
    by = {c["name"]: c for c in p["columns"]}
    assert p["rows"] == 5
    assert (by["portfolio"]["nulls"], by["portfolio"]["non_null"]) == (2, 3)                        # '' and '   ' count as empty
    assert (by["amount"]["nulls"], by["label"]["nulls"], by["footnote"]["nulls"], by["lei_code"]["nulls"]) == (1, 1, 4, 0)
    assert by["nsa"]["distinct"] == 2 and by["period"]["distinct"] == 2 and by["item"]["role"] == "key"
    assert by["nsa"]["null_pct"] == 0.0 and by["footnote"]["null_pct"] == 80.0
    assert [(t["value"], t["count"]) for t in by["nsa"]["top_values"]] == [("FR", 3), ("DE", 2)]
    assert by["amount"]["top_values"] == []                                                         # a measure has no top values
    assert p["amount"] == {"numeric": 3, "non_numeric": 1, "min": 1.0, "max": 5.0, "mean": pytest.approx(8 / 3)}


def test_profile_options_and_filters(db):
    _, fid = stage(db, banks(10) + AGG)
    p = A.profile(fid, db.schema, Filters(period="202003", exclude_aggregate=True), distinct=False, top=0)
    assert p["rows"] == 20 and all(c["distinct"] is None and c["top_values"] == [] for c in p["columns"])
    with pytest.raises(InvalidParameter, match="top"): A.profile(fid, db.schema, Filters(), top=99)


# ---------------------------------------------------------------------------------------------------- nulls
def test_nulls_by_period_matrix(db):
    rows = ["A0000000000000000001,DE,202003,I1,x,0,1,", "A0000000000000000002,DE,202003,I1,x,0,,", "A0000000000000000003,DE,202003,I2,x,,3,", "A0000000000000000004,DE,202006,I1,x,0,,", "A0000000000000000005,DE,202006,I2,x,0,5,"]
    _, fid = stage(db, rows)
    n = A.nulls(fid, db.schema, Filters(), "period", ["amount", "portfolio"])
    assert n["by"] == "period" and n["columns"] == ["amount", "portfolio"]
    g = {x["group"]: x for x in n["groups"]}
    assert g["202003"]["rows"] == 3 and g["202003"]["nulls"] == {"amount": 1, "portfolio": 1}
    assert g["202006"]["null_pct"] == {"amount": 50.0, "portfolio": 0.0}
    assert "lei_code" in A.nulls(fid, db.schema, Filters(), "period", None)["columns"]
    with pytest.raises(InvalidParameter, match="unknown column"): A.nulls(fid, db.schema, Filters(), "period", ["nope"])


def test_nulls_by_item_lists_the_worst_first(db):
    rows = ["A0000000000000000001,DE,202003,I1,One,0,1,", "A0000000000000000002,DE,202003,I1,One,0,,",
            "A0000000000000000003,DE,202003,I2,Two,0,,", "A0000000000000000004,DE,202003,I2,Two,0,abc,", "A0000000000000000005,DE,202003,I3,Three,0,5,"]
    _, fid = stage(db, rows)
    n = A.nulls(fid, db.schema, Filters(), "item", None, 10)
    assert [(g["group"], g["nulls"]["amount"], g["null_pct"]["amount"]) for g in n["groups"]] == [("I2", 2, 100.0), ("I1", 1, 50.0)]   # I3 has none
    assert A.nulls(fid, db.schema, Filters(), "item", None, 1)["groups"][0]["group"] == "I2"
    with pytest.raises(InvalidParameter): A.nulls(fid, db.schema, Filters(), "country")


# ------------------------------------------------------------------------------------------------ histogram
def reference_counts(values, lo, hi, bins):
    """Independent implementation: bin = floor((v - lo) / width), the maximum belongs to the last bin."""
    out = [0] * bins
    for v in values:
        out[min(int((v - lo) / (hi - lo) * bins), bins - 1)] += 1
    return out


def test_histogram_matches_an_independent_count(db):
    _, fid = stage(db, banks(40) + AGG)
    values = [10 + i * 0.5 for i in range(40)]
    h = hist(db, fid, bins=8)
    assert h["n"] == 40 and h["rows"] == 40 and h["nulls"] == 0 and h["scale"] == "linear"          # the aggregate bucket (amount 5) is excluded
    assert [b["count"] for b in h["bins"]] == reference_counts(values, 10, 29.5, 8) and sum(b["count"] for b in h["bins"]) == 40
    assert h["bins"][0]["x0"] == pytest.approx(10) and h["bins"][-1]["x1"] == pytest.approx(29.5) and h["outside"] == 0
    s = h["stats"]
    assert (s["min"], s["max"], s["median"], s["mean"]) == (10, 29.5, pytest.approx(19.75), pytest.approx(19.75))
    assert s["p25"] == pytest.approx(14.875) and s["p75"] == pytest.approx(24.625) and s["std"] == pytest.approx(0.5 * math.sqrt(40 * 41 / 12), rel=1e-9)
    assert h["label"] == "Item one" and h["period"] == "202003" and h["range"] == {"lo": 10, "hi": 29.5}


def test_histogram_clipping_counts_what_it_hides(db):
    rows = banks(100, periods=("202003",)) + ["LEI00000000000000999,DE,202003,I1,Item one,0,10000,"]          # 100 values 10.0 .. 59.5 and one outlier
    _, fid = stage(db, rows)
    full = hist(db, fid, bins=5)
    assert full["bins"][-1]["x1"] == 10000 and full["bins"][0]["count"] == 100 and full["outside"] == 0
    clipped = hist(db, fid, bins=5, clip="p01-p99")                       # p01 = 10.5, p99 = 59.5: the lowest value and the outlier are left out
    assert clipped["range"] == {"lo": pytest.approx(10.5), "hi": pytest.approx(59.5)} and clipped["outside"] == 2 and "percentiles" in clipped["note"]
    assert sum(b["count"] for b in clipped["bins"]) == 99 and sum(b["count"] for b in clipped["bins"]) + clipped["outside"] == 101
    iqr = hist(db, fid, bins=5, clip="iqr")                               # Tukey fences -15 and 85, limited to the data: only the outlier is left out
    assert iqr["range"] == {"lo": pytest.approx(10), "hi": pytest.approx(85)} and iqr["outside"] == 1 and sum(b["count"] for b in iqr["bins"]) == 100


def test_histogram_log_scale_and_non_positive_values(db):
    vals = [1, 10, 100, 1000, 10000, 0, -5]
    _, fid = stage(db, [f"A00000000000000000{i:02d},DE,202003,I1,x,0,{v}," for i, v in enumerate(vals)])
    h = hist(db, fid, bins=4, scale="log")
    assert [b["count"] for b in h["bins"]] == [1, 1, 1, 2] and h["non_positive"] == 2 and h["n"] == 7
    assert [round(h["bins"][i]["x1"] / h["bins"][i]["x0"], 3) for i in range(4)] == [10.0] * 4         # equal ratios
    assert h["bins"][0]["x0"] == pytest.approx(1) and h["bins"][-1]["x1"] == pytest.approx(10000) and h["outside"] == 0
    _, fid2 = stage(db, ["B0000000000000000001,DE,202003,I1,x,0,-1,", "B0000000000000000002,DE,202003,I1,x,0,-2,"], name="tr_cre_neg.csv")
    with pytest.raises(InvalidParameter, match="positive"): hist(db, fid2, scale="log")


def test_histogram_edge_cases(db):
    _, fid = stage(db, ["A0000000000000000001,DE,202003,I1,x,0,7,", "A0000000000000000002,DE,202003,I1,x,0,7,", "A0000000000000000003,DE,202003,I2,x,0,abc,", "A0000000000000000004,DE,202003,I2,x,0,,"])
    same = hist(db, fid, item="I1")
    assert same["bins"] == [{"x0": 7, "x1": 7, "count": 2}]                                             # all equal: one bin
    none = hist(db, fid, item="I2")
    assert (none["n"], none["nulls"], none["non_numeric"], none["bins"], none["stats"]) == (0, 1, 1, [], None)
    assert hist(db, fid, item="NOPE")["n"] == 0
    with pytest.raises(InvalidParameter, match="item is required"): A.histogram(fid, db.schema, Filters(), 10)
    for kw in ({"bins": 0}, {"bins": 999}, {"scale": "sqrt"}, {"clip": "winsor"}):
        with pytest.raises(InvalidParameter): A.histogram(fid, db.schema, Filters(item="I1"), **{"bins": 10, **kw})


def test_histogram_pools_periods_when_none_is_given(db):
    _, fid = stage(db, banks(10))
    assert A.histogram(fid, db.schema, Filters(item="I1"), 5)["n"] == 20
    assert A.histogram(fid, db.schema, Filters(item="I1", period="202006"), 5)["n"] == 10


# --------------------------------------------------------------------------------------------------- scatter
def sc(db, fid, **k):
    xi, yi = k.pop("x", ("I1", "202003")), k.pop("y", ("I2", "202003"))
    return A.scatter(fid, db.schema, Filters(item=xi[0], period=xi[1], exclude_aggregate=True, dims=k.pop("xdims", {})), Filters(item=yi[0], period=yi[1], exclude_aggregate=True, dims=k.pop("ydims", {})), **k)


def test_scatter_pairs_banks_and_computes_correlations(db):
    _, fid = stage(db, banks(40) + AGG)
    s = sc(db, fid)
    assert s["n_pairs"] == 40 and len(s["points"]) == 40 and s["sampled"] is False and s["agg"] == "single"
    assert all(math.isclose(p["y"], 2 * p["x"] + 1) for p in s["points"]) and {p["country"] for p in s["points"]} == {"DE"}
    assert s["stats"]["pearson"] == pytest.approx(1.0) and s["stats"]["spearman"] == pytest.approx(1.0)
    assert s["x"] == {"item": "I1", "period": "202003", "label": "Item one"} and s["y"]["label"] == "Item two"


def test_scatter_negative_and_changing_relationships(db):
    rows = [f"{lei(i)},DE,202003,I1,a,0,{i}," for i in range(30)] + [f"{lei(i)},DE,202003,I2,b,0,{100 - i}," for i in range(30)]
    s = sc(db, stage(db, rows)[1])
    assert s["stats"]["pearson"] == pytest.approx(-1.0) and s["stats"]["spearman"] == pytest.approx(-1.0)


def test_scatter_one_item_in_two_periods(db):
    rows = [f"{lei(i)},DE,202003,I1,a,0,{i}," for i in range(20)] + [f"{lei(i)},DE,202006,I1,a,0,{i * 3}," for i in range(15)]      # 5 banks left in the second period
    s = sc(db, stage(db, rows)[1], x=("I1", "202003"), y=("I1", "202006"))
    assert s["n_pairs"] == 15 and s["stats"]["pearson"] == pytest.approx(1.0)


def test_scatter_samples_reproducibly_and_reports_the_full_count(db):
    _, fid = stage(db, banks(40))
    a, b = sc(db, fid, max_points=15), sc(db, fid, max_points=15)
    assert a["n_pairs"] == 40 and len(a["points"]) == 15 and a["sampled"] is True and a["points"] == b["points"]    # same sample every time
    assert a["stats"]["pearson"] == pytest.approx(1.0)                                                              # statistics use all pairs, not the sample


def test_scatter_refuses_ambiguous_items_unless_told_how_to_combine(db):
    rows = [f"{lei(i)},DE,202003,I1,a,{p},{i + p}," for i in range(12) for p in (0, 1)] + [f"{lei(i)},DE,202003,I2,b,0,{i}," for i in range(12)]
    _, fid = stage(db, rows)
    with pytest.raises(InvalidParameter, match="several rows for 12 banks"): sc(db, fid)
    assert sc(db, fid, agg="sum")["n_pairs"] == 12
    narrowed = sc(db, fid, xdims={"portfolio": "1"})
    assert narrowed["n_pairs"] == 12 and narrowed["points"][0]["x"] - 1 == pytest.approx(next(p["y"] for p in narrowed["points"] if p["lei"] == narrowed["points"][0]["lei"]) , abs=100)
    assert sc(db, fid, agg="mean", max_points=50)["stats"]["pearson"] == pytest.approx(1.0)


def test_scatter_parameter_errors(db):
    _, fid = stage(db, banks(12))
    with pytest.raises(InvalidParameter, match="agg"): sc(db, fid, agg="median")
    with pytest.raises(InvalidParameter, match="max_points"): sc(db, fid, max_points=3)
    with pytest.raises(InvalidParameter, match="x_item and x_period"): A.scatter(fid, db.schema, Filters(item="I1"), Filters(item="I2", period="202003"), "single", 100)
    empty = sc(db, fid, x=("NOPE", "202003"))
    assert (empty["n_pairs"], empty["points"], empty["stats"]["pearson"]) == (0, [], None)
