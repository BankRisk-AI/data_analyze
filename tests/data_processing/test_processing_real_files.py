"""The processing module on the prepared 2020A EBA files (skipped when the layout is unavailable).
The expected numbers were measured on these files with an independent SQL check."""
import os
import time

import pytest
from pathlib import Path

from app.modules.eba_ingest import ingest
from app.modules.eba_processing.application import analytics as A
from app.modules.eba_processing.application import datasets as D
from app.modules.eba_processing.application import validation as V
from app.modules.eba_processing.domain import Filters

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL = os.path.join(os.environ.get("EBA_REAL_DIR") or str(PROJECT_ROOT / "eba_prepared"), "2020A")
FILES = ["tr_oth.csv", "tr_cre.csv", "tr_mrk.csv"]
pytestmark = [
    pytest.mark.data_processing,
    pytest.mark.skipif(not os.path.isdir(REAL), reason="EBA_REAL_DIR prepared layout not found"),
]


@pytest.mark.slow
def test_original_2020_files(db):
    rep = ingest([os.path.join(REAL, f) for f in FILES], db.storage, schema=db.schema)
    imp = rep.import_id
    oth, cre, mrk = [f.file_id for f in rep.files]

    # --- datasets: rows and the (period, banks, rows) triples, aggregate bucket excluded from banks and rows
    ds = {d["file_type"]: d for d in D.datasets_of_import(imp, db.schema)}
    assert {k: v["rows"] for k, v in ds.items()} == {"tr_oth": 53526, "tr_cre": 396232, "tr_mrk": 13668}
    assert [(p["period"], p["banks"], p["rows"]) for p in ds["tr_oth"]["periods"]] == [("202003", 131, 26070), ("202006", 135, 27034)]
    assert [(p["banks"], p["rows"]) for p in ds["tr_cre"]["periods"]] == [(131, 182195), (135, 210083)]
    assert [(p["banks"], p["rows"]) for p in ds["tr_mrk"]["periods"]] == [(131, 6681), (135, 6885)]

    # --- profile of tr_oth
    p = A.profile(oth, db.schema, Filters())
    by = {c["name"]: c for c in p["columns"]}
    assert by["footnote"]["nulls"] == 52432 and by["amount"]["nulls"] == 0 and by["lei_code"]["distinct"] == 136 and by["period"]["distinct"] == 2
    assert p["amount"]["numeric"] == 53526 and p["amount"]["non_numeric"] == 0
    assert p["amount"]["min"] == pytest.approx(-32278.247323) and p["amount"]["max"] == pytest.approx(2575724.25976634)
    assert A.nulls(oth, db.schema, Filters(), "item")["groups"] == []                                   # no item has an empty amount

    # --- histogram of the CET1 ratio (item 2020140) in 202006
    h = A.histogram(oth, db.schema, Filters(item="2020140", period="202006", exclude_aggregate=True), 10)
    assert h["n"] == 135 and [b["count"] for b in h["bins"]] == [120, 10, 2, 1, 0, 1, 0, 0, 0, 1] and h["stats"]["median"] == pytest.approx(0.1613765071)
    assert h["label"].startswith("COMMON EQUITY TIER 1 CAPITAL RATIO")

    # --- scatter: CET1 ratio against Tier 1 ratio (item 2020141) in 202006
    s = A.scatter(oth, db.schema, Filters(item="2020140", period="202006", exclude_aggregate=True), Filters(item="2020141", period="202006", exclude_aggregate=True), "single", 2000)
    assert s["n_pairs"] == 135 and not s["sampled"] and s["stats"]["pearson"] == pytest.approx(0.98909, abs=1e-4) and s["stats"]["spearman"] == pytest.approx(0.94893, abs=1e-4)

    # --- validation of the three files: no error, no warning; information only
    started = time.perf_counter()
    report = V.run_validation(imp, db.schema)
    assert time.perf_counter() - started < 60
    assert (report.errors, report.warnings, report.infos, report.can_proceed) == (0, 0, 9, True)
    rules = {f.file_type: {i.rule: i for i in f.issues} for f in report.files}
    assert {k: v["V10"].affected_rows for k, v in rules.items()} == {"tr_oth": 4, "tr_cre": 4, "tr_mrk": 4}                 # four banks appear only in the second period
    assert {k: v["V11"].affected_rows for k, v in rules.items()} == {"tr_oth": 5068, "tr_cre": 66856, "tr_mrk": 488}       # heavy-tailed sizes: information, not an error
    assert {k: v["V12"].affected_rows for k, v in rules.items()} == {"tr_oth": 422, "tr_cre": 3954, "tr_mrk": 102}
    assert all(v[r].passed for v in rules.values() for r in ("V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V13"))
    db.cur.execute("SELECT status FROM import_batch WHERE import_id = %s", (imp,))
    assert db.cur.fetchone()[0] == "validated"
