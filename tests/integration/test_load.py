from openpyxl import Workbook

from app.core.database import connect
from app.modules.eba_ingest import ingest
from app.modules.eba_ingest.application.load_service import LoadError, run_load
from app.modules.eba_public_analysis.application.datasets import preview


def _book(path, rows, sheet="Sheet"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_validated_import_is_promoted_and_staging_is_dropped(db):
    lei_code = "LEI00000000000000001"
    data = db.dir / "tr_cre_case.csv"
    data.write_text(
        "LEI_Code,NSA,Period,Item,Label,Portfolio,Amount,footnote\n"
        f"{lei_code},DE,202003,I1,Item one,0,12.5,\n", encoding="cp1252"
    )
    sdd = db.dir / "SDD_case.xlsx"
    _book(sdd, [["Item", "Label", "Category", "Dataset", "Item_TR_2020"],
                ["STD1", "Item one", "CAPITAL", "tr_cre", "I1"]])
    metadata = db.dir / "TR_Metadata_case.xlsx"
    _book(metadata, [["title"], ["LEI_Code", "Name", "Country", "Finrep", "LEI_Code_2019"],
                     [lei_code, "Bank", "DE", "Yes", ""]], "Bank list")

    report = ingest([str(data), str(sdd), str(metadata)], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    run_load(report.import_id, db.schema)

    db.cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (report.import_id,))
    assert db.cur.fetchone() == ("loaded",)
    db.cur.execute("SELECT version_id FROM dataset_version WHERE import_id=%s", (report.import_id,))
    public = preview(db.cur.fetchone()[0], "tr_cre", db.schema, 1, 10)
    assert public["dataset"] == "cre"
    db.cur.execute("SELECT count(*), sum(amount) FROM fact_cre")
    assert db.cur.fetchone() == (1, 12.5)
    db.cur.execute("SELECT to_regclass(%s)", (f"staging.f{report.files[0].file_id}",))
    assert db.cur.fetchone() == (None,)
    db.cur.execute("SELECT lei_code, item, amount FROM v_tr_cre")
    assert db.cur.fetchone() == (lei_code, "I1", 12.5)
    try:
        run_load(report.import_id, db.schema)
    except LoadError as exc:
        assert "already loaded" in str(exc)
    else:
        raise AssertionError("a loaded import was accepted for a second load")
    db.cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (report.import_id,))
    assert db.cur.fetchone() == ("loaded",)


def test_load_failure_keeps_staging_and_environment_can_keep_successful_staging(db, monkeypatch):
    data = db.dir / "tr_cre_bad.csv"
    data.write_text("LEI_Code,NSA,Period,Item,Label,Portfolio,Amount,extra\n"
                    "LEI00000000000000001,DE,202003,I1,Item one,0,12.5,x\n", encoding="cp1252")
    sdd = db.dir / "SDD_bad.xlsx"
    _book(sdd, [["Item", "Label", "Category", "Dataset", "Item_TR_2020"], ["I1", "Item one", "CAPITAL", "tr_cre", "I1"]])
    report = ingest([str(data), str(sdd)], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    try:
        run_load(report.import_id, db.schema)
    except LoadError as exc:
        assert "schema-mismatch" in str(exc)
    else:
        raise AssertionError("schema mismatch was accepted")
    db.cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (report.import_id,))
    assert db.cur.fetchone() == ("failed",)
    db.cur.execute("SELECT to_regclass(%s)", (f"staging.f{report.files[0].file_id}",))
    assert db.cur.fetchone()[0] is not None

    good = db.dir / "tr_cre_good.csv"
    good.write_text("LEI_Code,NSA,Period,Item,Label,Portfolio,Amount,footnote\n"
                    "LEI00000000000000001,DE,202003,I1,Item one,0,12.5,\n", encoding="cp1252")
    # A new import is used because a failed import's original file is immutable.
    monkeypatch.setenv("EBA_DROP_STAGING_AFTER_LOAD", "false")
    report = ingest([str(good), str(sdd)], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    run_load(report.import_id, db.schema)
    db.cur.execute("SELECT to_regclass(%s)", (f"staging.f{report.files[0].file_id}",))
    assert db.cur.fetchone()[0] is not None
