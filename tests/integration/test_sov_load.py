import pytest
from openpyxl import Workbook

from app.modules.eba_ingest import ingest
from app.modules.eba_ingest.application.load_service import LoadError, run_load


def _sdd(path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Item", "Label", "Category", "Dataset"])
    ws.append(["S1", "Sovereign item", "CAPITAL", "tr_sov"])
    wb.save(path)


def _write(path, rows, header="LEI_Code,NSA,Period,Item,Label,Country,Accounting_Portfolio,Amount\n"):
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_sov_loads_multiple_files_excludes_aggregate_and_allows_missing_dimensions(db):
    first = db.dir / "tr_sov_2016.csv"
    second = db.dir / "tr_sov_2016_b.csv"
    _write(first, [
        "AAAAAAAAAAAAAAAAAAAA,DE,201606,S1,Label,0,1,10",
        "XXXXXXXXXXXXXXXXXXXX,DE,201606,S1,Label,0,1,99",
    ])
    _write(second, [
        "AAAAAAAAAAAAAAAAAAAA,DE,201609,S1,Label,1,2,20",
    ], "LEI_Code,NSA,Period,Item,Label,Country,Accounting_Portfolio,Maturity,Amount,Row,Column,Sheet\n")
    # The source has no maturity in the first file and has audit locations in the second.
    second.write_text(
        "LEI_Code,NSA,Period,Item,Label,Country,Accounting_Portfolio,Maturity,Amount,Row,Column,Sheet\n"
        "AAAAAAAAAAAAAAAAAAAA,DE,201609,S1,Label,1,2,8,20,3,C,Sov\n",
        encoding="utf-8",
    )
    sdd = db.dir / "SDD.xlsx"
    _sdd(sdd)
    report = ingest([str(first), str(second), str(sdd)], db.storage, schema=db.schema, edition_label="2016")
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    run_load(report.import_id, db.schema)
    db.cur.execute("SELECT count(*), coalesce(sum(amount), 0) FROM fact_sov")
    assert db.cur.fetchone() == (2, 30.0)
    db.cur.execute("SELECT maturity, source_row, source_column, source_sheet FROM fact_sov ORDER BY amount")
    assert db.cur.fetchall() == [(None, None, None, None), ("8", "3", "C", "Sov")]


def test_sov_duplicate_identity_rolls_back(db):
    data = db.dir / "tr_sov_duplicate.csv"
    _write(data, [
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,S1,Label,0,1,10",
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,S1,Label,0,1,20",
    ])
    sdd = db.dir / "SDD.xlsx"
    _sdd(sdd)
    report = ingest([str(data), str(sdd)], db.storage, schema=db.schema, edition_label="2020")
    db.cur.execute("UPDATE import_batch SET status='validated' WHERE import_id=%s", (report.import_id,))
    with pytest.raises(LoadError, match="duplicate-facts: fact_sov"):
        run_load(report.import_id, db.schema)
    db.cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (report.import_id,))
    assert db.cur.fetchone() == ("failed",)
    db.cur.execute("SELECT count(*) FROM fact_sov")
    assert db.cur.fetchone() == (0,)
