import time

import pytest
from openpyxl import Workbook

from app.core.preflight import collision_check
from app.modules.eba_ingest import ingest
from app.modules.eba_ingest.application.load_service import LoadError, run_load


def _book(path, rows, sheet="Sheet"):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def _load_oth(db, csv_rows, metadata_rows=None, sdd_rows=None):
    data = db.dir / "tr_oth_set_based.csv"
    data.write_text(
        "LEI_Code,NSA,Period,Item,Label,Assets_FV,Amount,Fin_end_year,N_quarters,Footnote\n"
        + "\n".join(csv_rows)
        + "\n",
        encoding="utf-8",
    )
    paths = [str(data)]
    if sdd_rows is not None:
        sdd = db.dir / "SDD_set_based.xlsx"
        _book(sdd, sdd_rows)
        paths.append(str(sdd))
    if metadata_rows is not None:
        metadata = db.dir / "TR_Metadata_set_based.xlsx"
        _book(metadata, metadata_rows, "Bank list")
        paths.append(str(metadata))
    report = ingest(paths, db.storage, user_id=1, edition_label="2020", schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    run_load(report.import_id, db.schema)
    return report


def test_set_based_load_matches_expected_facts_and_resolution_counts(db):
    leis = ["AAAAAAAAAAAAAAAAAAAA", "BBBBBBBBBBBBBBBBBBBB"]
    rows = [
        f"{leis[0]},DE,202003,I1,Item one,10,1,2020,4,",
        f"{leis[1]},FR,202003,I1,Item one,11,2,2020,4,",
        f"{leis[0]},DE,202003,I2,Item two,12,3,2020,4,",
        f"{leis[1]},FR,202003,I2,Item two,13,4,2020,4,",
        f"{leis[0]},DE,202006,I1,Item one,14,5,2020,4,",
        f"{leis[1]},FR,202006,I1,Item one,15,6,2020,4,",
        f"{leis[0]},DE,202006,I2,Item two,16,7,2020,4,",
        f"{leis[1]},FR,202006,I2,Item two,17,8,2020,4,",
        "XXXXXXXXXXXXXXXXXXXX,OT,202003,I1,Item one,0,999,2020,4,",
    ]
    report = _load_oth(
        db,
        rows,
        [[
            "LEI_Code", "Name", "Country", "Finrep",
        ], [leis[0], "A", "DE", "Yes"], [leis[1], "B", "FR", "Yes"]],
        [["Item", "Label", "Category", "Dataset"],
         ["I1", "Item one", "CAPITAL", "tr_oth"],
         ["I2", "Item two", "P&L", "tr_oth"]],
    )
    db.cur.execute(
        """SELECT v.year, v.quarter, count(*), sum(f.amount), count(DISTINCT f.bank_id),
                  count(DISTINCT f.indicator_id)
           FROM fact_oth f JOIN dataset_version v USING (version_id)
           WHERE v.import_id=%s GROUP BY v.year, v.quarter ORDER BY 1, 2""",
        (report.import_id,),
    )
    assert db.cur.fetchall() == [(2020, 1, 4, 10.0, 2, 2), (2020, 2, 4, 26.0, 2, 2)]
    db.cur.execute(
        "SELECT detail->'counts' FROM decision_log WHERE import_id=%s AND step='item_resolution'",
        (report.import_id,),
    )
    assert db.cur.fetchone()[0] == {"unmapped": 8}


def test_full_data_decisions_are_applied_before_collision_check(db):
    data = db.dir / "tr_cre_decision.csv"
    data.write_text(
        "LEI_Code,NSA,Period,Item,Label,Portfolio,Country,Country_rank,Exposure,Status,Perf_status,NACE_codes,Amount\n"
        "529900GGYMNGRQTDOO93,NL,201912,2020501,Original Exposure,1,0,0,0,0,0,0,10\n"
        "529900GGYMNGRQTDOO93,NL,201912,2020501,Original Exposure,1,0,0,0,0,0,0,20\n"
        "529900GGYMNGRQTDOO93,NL,201912,2020502,Original Exposure,1,0,0,303,0,0,0,30\n"
        "529900GGYMNGRQTDOO93,NL,201912,2020502,Original Exposure,1,0,0,303,0,0,0,40\n",
        encoding="utf-8",
    )
    report = ingest([str(data)], db.storage, user_id=1, edition_label="2020S", schema=db.schema)
    assert collision_check(db.cur, report.import_id) == []


def test_previous_lei_resolves_without_creating_a_bank_and_blank_values_are_null(db):
    current = "CCCCCCCCCCCCCCCCCCCC"
    previous = "DDDDDDDDDDDDDDDDDDDD"
    report = _load_oth(
        db,
        [f"{previous},DE,202003,I1,Item one, ,not-a-number,,,",
         f"{current},DE,202003,I1,Item one,2,3,2020,4,ok"],
        [["LEI_Code", "Name", "Country", "Finrep", "LEI_Code_2019"],
         [current, "Bank", "DE", "Yes", previous]],
        [["Item", "Label", "Category", "Dataset"], ["I1", "Item one", "CAPITAL", "tr_oth"]],
    )
    db.cur.execute("SELECT bank_id FROM bank WHERE lei=%s", (current,))
    bank_id = db.cur.fetchone()[0]
    db.cur.execute("SELECT count(*) FROM bank WHERE lei IN (%s, %s)", (current, previous))
    assert db.cur.fetchone() == (1,)
    db.cur.execute(
        "SELECT bank_id, amount, assets_fv, footnote FROM fact_oth f JOIN dataset_version v USING (version_id) WHERE v.import_id=%s ORDER BY amount NULLS FIRST",
        (report.import_id,),
    )
    assert db.cur.fetchall() == [(bank_id, None, None, None), (bank_id, 3.0, "2", "ok")]


def test_duplicate_fact_identity_rolls_back_the_load(db):
    data = db.dir / "tr_oth_duplicate.csv"
    data.write_text(
        "LEI_Code,NSA,Period,Item,Label,Assets_FV,Amount,Fin_end_year,N_quarters,Footnote\n"
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,I1,Item one,1,1,2020,4,\n"
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,I1,Item one,1,2,2020,4,\n",
        encoding="utf-8",
    )
    sdd = db.dir / "SDD_duplicate.xlsx"
    _book(sdd, [["Item", "Label", "Category", "Dataset"], ["I1", "Item one", "CAPITAL", "tr_oth"]])
    report = ingest([str(data), str(sdd)], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    with pytest.raises(LoadError, match="duplicate-facts: fact_oth"):
        run_load(report.import_id, db.schema)
    db.cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (report.import_id,))
    assert db.cur.fetchone() == ("failed",)
    db.cur.execute("SELECT count(*) FROM fact_oth")
    assert db.cur.fetchone() == (0,)
    db.cur.execute("SELECT count(*) FROM dataset_version WHERE import_id=%s AND is_active", (report.import_id,))
    assert db.cur.fetchone() == (0,)


@pytest.mark.slow
def test_set_based_load_100k_rows_under_five_seconds(db, monkeypatch):
    rows = [
        f"{index % 100:020d},DE,202003,I1,Item one,{index},1,2020,4,"
        for index in range(100_000)
    ]
    data = db.dir / "tr_oth_100k.csv"
    data.write_text(
        "LEI_Code,NSA,Period,Item,Label,Assets_FV,Amount,Fin_end_year,N_quarters,Footnote\n"
        + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    metadata = db.dir / "TR_Metadata_100k.xlsx"
    _book(
        metadata,
        [["LEI_Code", "Name", "Country", "Finrep"]]
        + [[f"{index:020d}", f"Bank {index}", "DE", "Yes"] for index in range(100)],
        "Bank list",
    )
    sdd = db.dir / "SDD_100k.xlsx"
    _book(sdd, [["Item", "Label", "Category", "Dataset"], ["I1", "Item one", "CAPITAL", "tr_oth"]])
    report = ingest(
        [str(data), str(sdd), str(metadata)],
        db.storage,
        user_id=1,
        edition_label="2020",
        schema=db.schema,
    )
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    monkeypatch.setenv("EBA_DROP_STAGING_AFTER_LOAD", "false")
    started = time.perf_counter()
    run_load(report.import_id, db.schema)
    elapsed = time.perf_counter() - started
    assert elapsed < 10
