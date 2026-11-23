import pytest

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.application import datasets as D
from app.modules.eba_processing.domain import Filters
from app.modules.eba_processing.domain.exceptions import DatasetNotFound, ImportNotFound
from app.modules.eba_ingest import drop_staging
from helpers import banks, lei, stage

AGG = ["XXXXXXXXXXXXXXXXXXXX,OT,202003,I1,Item one,0,5,"]


def test_datasets_describe_columns_roles_and_periods(db):
    imp, fid = stage(db, banks(40) + AGG)
    [d] = D.datasets_of_import(imp, db.schema)
    assert (d["file_id"], d["file_type"], d["rows"]) == (fid, "tr_cre", 40 * 2 * 2 + 1)
    assert [(c["name"], c["role"]) for c in d["columns"]] == [("lei_code", "key"), ("nsa", "key"), ("period", "key"), ("item", "key"), ("label", "label"), ("portfolio", "dimension"), ("amount", "measure"), ("footnote", "annotation")]
    assert [(p["period"], p["year"], p["quarter"], p["banks"], p["rows"]) for p in d["periods"]] == [("202003", 2020, 1, 40, 80), ("202006", 2020, 2, 40, 80)]   # aggregate bucket excluded
    assert D.dataset_info(fid, db.schema)["rows"] == d["rows"]


def test_dropped_staging_and_unknown_ids(db):
    imp, fid = stage(db, banks(3))
    drop_staging(imp, db.schema)
    assert D.datasets_of_import(imp, db.schema) == []
    with pytest.raises(DatasetNotFound, match="dropped"): D.dataset_info(fid, db.schema)
    with pytest.raises(ImportNotFound): D.datasets_of_import(9999, db.schema)
    with pytest.raises(DatasetNotFound, match="no file"): D.dataset_info(9999, db.schema)


def test_preview_paging_and_totals(db):
    _, fid = stage(db, banks(40))
    p1 = D.preview(fid, db.schema, Filters(), page=1, page_size=50)
    assert (p1["total"], p1["pages"], len(p1["rows"]), p1["page"]) == (160, 4, 50, 1)
    p4 = D.preview(fid, db.schema, Filters(), page=4, page_size=50)
    assert len(p4["rows"]) == 10 and p1["rows"][0] != p4["rows"][0]
    assert D.preview(fid, db.schema, Filters(), page=9, page_size=50)["rows"] == []       # beyond the last page: empty, not an error
    assert p1["rows"][0]["lei_code"] == lei(0) and p1["rows"][0]["amount"] == "10.0"      # rows exactly as loaded (text), in file order
    assert [c["name"] for c in p1["columns"]][:2] == ["lei_code", "nsa"] and p1["elapsed_ms"] >= 0


def test_preview_sorts_amounts_numerically(db):
    _, fid = stage(db, ["A0000000000000000001,DE,202003,I1,x,0,9", "A0000000000000000002,DE,202003,I1,x,0,10", "A0000000000000000003,DE,202003,I1,x,0,100", "A0000000000000000004,DE,202003,I1,x,0,"])
    asc = [r["amount"] for r in D.preview(fid, db.schema, Filters(), sort="amount", order="asc")["rows"]]
    desc = [r["amount"] for r in D.preview(fid, db.schema, Filters(), sort="amount", order="desc")["rows"]]
    assert asc == ["9", "10", "100", None] and desc == ["100", "10", "9", None]            # numeric, not alphabetical; empty last
    by_lei = [r["lei_code"] for r in D.preview(fid, db.schema, Filters(), sort="lei_code", order="desc")["rows"]]
    assert by_lei == sorted(by_lei, reverse=True)


def test_preview_filters_combine(db):
    _, fid = stage(db, banks(40) + AGG)
    f = lambda **k: D.preview(fid, db.schema, Filters(**k), page_size=1000)
    assert f(period="202003")["total"] == 81
    assert f(period="202003", item="I2")["total"] == 40
    assert f(lei=lei(3))["total"] == 4
    assert f(dims={"portfolio": "0"})["total"] == 161 and f(dims={"portfolio": "9"})["total"] == 0
    assert f(exclude_aggregate=True)["total"] == 160 and f()["total"] == 161
    assert f(period="202003", item="I1", exclude_aggregate=True, dims={"portfolio": "0"})["total"] == 40


def test_preview_refuses_anything_that_is_not_a_column_or_a_value(db):
    _, fid = stage(db, banks(3))
    for bad in ["amount; DROP TABLE source_file", "nope", "lei_code) --", "1"]:
        with pytest.raises(InvalidParameter, match="unknown column"): D.preview(fid, db.schema, Filters(), sort=bad)
        with pytest.raises(InvalidParameter, match="unknown column"): D.preview(fid, db.schema, Filters(dims={bad: "x"}))
    assert D.preview(fid, db.schema, Filters(item="I1' OR '1'='1"))["total"] == 0           # values are bound parameters, never SQL
    assert D.preview(fid, db.schema, Filters(lei="x'; DROP TABLE import_batch; --"))["total"] == 0
    db.cur.execute("SELECT count(*) FROM import_batch"); assert db.cur.fetchone()[0] == 1   # the tables are still there
    with pytest.raises(InvalidParameter, match="page_size"): D.preview(fid, db.schema, Filters(), page_size=5000)
    with pytest.raises(InvalidParameter, match="page starts"): D.preview(fid, db.schema, Filters(), page=0)
    with pytest.raises(InvalidParameter, match="order"): D.preview(fid, db.schema, Filters(), order="sideways")


def test_item_catalogue(db):
    rows = banks(10) + ["LEI00000000000000100,DE,202003,I3,Three,0,", "LEI00000000000000101,DE,202003,I3,Three b,0,abc", "LEI00000000000000102,DE,202003,I3,Three,0,7"]
    _, fid = stage(db, rows)
    cat = D.items(fid, db.schema, Filters())
    assert cat["total"] == 3 and [i["item"] for i in cat["items"]] == ["I1", "I2", "I3"]
    i1, i3 = cat["items"][0], cat["items"][2]
    assert (i1["rows"], i1["banks"], i1["null_amount"], i1["labels"]) == (20, 10, 0, 1)
    assert (i3["rows"], i3["null_amount"], i3["non_numeric_amount"], i3["labels"]) == (3, 1, 1, 2)
    assert [i["item"] for i in D.items(fid, db.schema, Filters(), q="two")["items"]] == ["I2"]             # label search, case-insensitive
    assert D.items(fid, db.schema, Filters(), q="%")["total"] == 0                                         # % is a literal, not a wildcard
    assert D.items(fid, db.schema, Filters(period="202006"))["items"][0]["rows"] == 10
    assert D.items(fid, db.schema, Filters(), page=2, page_size=2)["items"][0]["item"] == "I3"
