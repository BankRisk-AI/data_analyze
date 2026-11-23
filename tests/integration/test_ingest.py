import os, stat, pytest
from openpyxl import Workbook
from app.modules.eba_ingest import ingest
from app.modules.eba_ingest.domain import (
    DuplicateFile,
    FileTooLarge,
    UnreadableFile,
)
from app.modules.eba_ingest.domain.services.file_detector import classify_name, normalise_header, missing_required
from app.modules.eba_ingest.infrastructure.storage.storage import store
from app.modules.eba_ingest.application.load_service import _metadata
from app.modules.eba_ingest.infrastructure.readers.readers import xlsx_bank_list_sheet
from app.modules.eba_processing.application.validation import run_validation
from conftest import write_csv, HEADER

ROWS = ["AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,CET1 ratio,0.15,", "BBBBBBBBBBBBBBBBBBBB,FR,202003,2020140,CET1 ratio,0.12,",
        "AAAAAAAAAAAAAAAAAAAA,DE,202006,2020140,CET1 ratio \u2013 transitional,0.16,", "BBBBBBBBBBBBBBBBBBBB,FR,202006,2020140,CET1 ratio,0.13,",
        "XXXXXXXXXXXXXXXXXXXX,OT,202003,2020140,CET1 ratio,0.50,", "xxxxxxxxxxxxxxxxxxxx,OT,202006,2020140,CET1 ratio,0.50,"]
def run(h, paths, **kw): return ingest(paths, h.storage, schema=h.schema, **kw)
def count(h, table): h.cur.execute(f"SELECT count(*) FROM {table}"); return h.cur.fetchone()[0]

def test_names_and_headers():
    assert [classify_name(n) for n in ["tr_oth_2.csv", "TR_CRE.xlsx", "tr_mrk.csv", "tr_sov_x.csv", "SDD_2.xlsx", "TR_Metadata_2.xlsx", "notes.txt"]] == ["tr_oth", "tr_cre", "tr_mrk", "tr_sov", "SDD", "TR_Metadata", None]
    assert normalise_header(["LEI_Code", " Period ", "Fin end year"]) == ["lei_code", "period", "fin_end_year"]
    assert missing_required(["lei_code", "period"]) == ["nsa", "item", "amount"]
    with pytest.raises(ValueError): normalise_header(["a", "A"])

def test_encoding_detection_and_immutable_storage(tmp_path):
    utf8 = tmp_path / "a.csv"; utf8.write_bytes("x,y\n\u00e9,1\n".encode("utf-8")); cp = tmp_path / "b.csv"; cp.write_bytes(b"x,y\n\x96,1\n")
    s1 = store(str(utf8), str(tmp_path / "st"), 10**6, True); s2 = store(str(cp), str(tmp_path / "st"), 10**6, True)
    assert s1[3] == "utf-8" and s2[3] == "cp1252"
    assert len(s1[0]) == 64 and os.path.exists(s1[2]) and not (os.stat(s1[2]).st_mode & stat.S_IWUSR)   # read-only
    again = store(str(utf8), str(tmp_path / "st"), 10**6, True); assert again[0] == s1[0] and again[4] is False   # same content: stored once

def test_small_csv_is_staged_with_periods_and_aggregate(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    r = run(db, [p], user_id=1, edition_label="2020")
    f = r.files[0]
    assert r.status == "uploaded" and f.recognised and f.file_type == "tr_oth" and f.encoding == "cp1252"
    assert f.rows == 6 and f.aggregate_rows == 2                                  # X in upper and lower case
    assert [(x.year, x.quarter, x.banks, x.rows) for x in f.pairs] == [(2020, 1, 2, 2), (2020, 2, 2, 2)]
    assert count(db, f"staging.f{f.file_id}") == 6
    db.cur.execute(f"SELECT label FROM staging.f{f.file_id} WHERE period='202006' AND lei_code='AAAAAAAAAAAAAAAAAAAA'"); assert db.cur.fetchone()[0] == "CET1 ratio \u2013 transitional"   # the cp1252 dash survived
    db.cur.execute("SELECT status, edition_label, created_by FROM import_batch"); assert db.cur.fetchall() == [("uploaded", "2020", 1)]
    db.cur.execute("SELECT file_type, encoding, sha256 FROM source_file"); ft, enc, sha = db.cur.fetchone(); assert (ft, enc, len(sha)) == ("tr_oth", "cp1252", 64)
    assert count(db, "job") == 1 and count(db, "decision_log") == 1 and count(db, "audit_log") == 1

def test_label_less_csv_stages_and_validates(db):
    p = db.dir / "tr_oth_no_label.csv"
    p.write_text("LEI_Code,NSA,Period,Item,Amount\nAAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,0.15\n", encoding="cp1252")
    report = run(db, [str(p)])
    file = report.files[0]
    assert file.recognised and file.rows == 1
    db.cur.execute(f"SELECT label FROM staging.f{file.file_id}")
    assert db.cur.fetchone() == (None,)
    validation = run_validation(report.import_id, db.schema)
    assert validation.can_proceed

def test_grouped_thousands_amount_is_normalised(db):
    p = db.dir / "tr_oth_grouped_amount.csv"
    p.write_text(
        "LEI_Code,NSA,Period,Item,Label,Amount\n"
        "AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,Ratio,\"1,234.50\"\n",
        encoding="cp1252",
    )
    report = run(db, [str(p)])
    file = report.files[0]
    db.cur.execute(f"SELECT amount FROM staging.f{file.file_id}")
    assert db.cur.fetchone() == ("1234.50",)
    assert run_validation(report.import_id, db.schema).can_proceed

def test_amount_normalisation_accepts_only_thousands_grouping(db):
    values = ["74,672.4857", "1,234,567", "-1,000.5", "1,5", "12,34"]
    paths = []
    for index, value in enumerate(values):
        path = db.dir / f"tr_oth_amount_{index}.csv"
        path.write_text(
            "LEI_Code,NSA,Period,Item,Label,Amount\n"
            f"AAAAAAAAAAAAAAAAAAAA,DE,202003,I{index},Item,\"{value}\"\n",
            encoding="cp1252",
        )
        paths.append(str(path))
    report = run(db, paths)
    got = []
    for file in report.files:
        db.cur.execute(f"SELECT amount FROM staging.f{file.file_id}")
        got.append(db.cur.fetchone()[0])
    assert got == ["74672.4857", "1234567", "-1000.5", "1,5", "12,34"]
    assert [file.normalised_amounts for file in report.files] == [1, 1, 1, 0, 0]

@pytest.mark.parametrize("sheet", ["Bank list", "Banks list", "List of Institutions", "List of Financial Institutions"])
def test_metadata_reader_finds_bank_list_sheet_and_previous_leis(tmp_path, sheet):
    path = tmp_path / f"{sheet.replace(' ', '_')}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["title row"])
    ws.append(["LEI_Code", "Name", "Country", "Finrep", "LEI_Code_TR16", "LEI_Code_used_for_2014_stress_test"])
    ws.append(["AAAAAAAAAAAAAAAAAAAA", "Bank", "DE", "Yes", "BBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCC"])
    wb.save(path)
    assert xlsx_bank_list_sheet(str(path)) == sheet
    assert _metadata(str(path)) == [(
        "AAAAAAAAAAAAAAAAAAAA", "Bank", "DE", True,
        ["BBBBBBBBBBBBBBBBBBBB", "CCCCCCCCCCCCCCCCCCCC"],
    )]

def test_metadata_reader_accepts_2015_bank_name(tmp_path):
    path = tmp_path / "TR_Metadata.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Institutions"
    ws.append(["title row"])
    ws.append(["LEI_Code", "Bank_Name", "Country_Code"])
    ws.append(["AAAAAAAAAAAAAAAAAAAA", "Legacy Bank", "DE"])
    wb.save(path)
    assert _metadata(str(path)) == [(
        "AAAAAAAAAAAAAAAAAAAA", "Legacy Bank", "DE", False, [],
    )]

def test_same_file_twice_in_one_upload_is_refused(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    with pytest.raises(DuplicateFile): run(db, [p, p])
    assert count(db, "import_batch") == 0

def test_file_already_loaded_is_refused_but_unloaded_is_accepted(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    first = run(db, [p]); again = run(db, [p]); assert again.import_id != first.import_id      # not loaded yet: allowed
    db.cur.execute("UPDATE import_batch SET status = 'loaded' WHERE import_id = %s", (first.import_id,))
    with pytest.raises(DuplicateFile, match="already loaded"): run(db, [p])

def test_too_large_is_refused_before_anything_is_created(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    with pytest.raises(FileTooLarge): run(db, [p], max_bytes=100)
    assert count(db, "import_batch") == 0 and not os.path.exists(db.storage + "/tmp") or not [f for _, _, fs in os.walk(db.storage) for f in fs if f.endswith(".csv")]

def test_unrecognised_files_reject_the_import_but_keep_the_lineage(db):
    p = db.dir / "notes.csv"; p.write_text("a,b\n1,2\n")
    r = run(db, [str(p)]); assert r.status == "rejected" and "no recognised" in r.error and r.files[0].reason
    db.cur.execute("SELECT status FROM import_batch"); assert db.cur.fetchone()[0] == "rejected"
    db.cur.execute("SELECT status, error FROM job"); assert db.cur.fetchone()[0] == "failed"

def test_missing_columns_are_reported_not_staged(db):
    p = write_csv(db.dir / "tr_cre_x.csv", ["A,1"], header="LEI_Code,Value\n")
    r = run(db, [p]); f = r.files[0]
    assert not f.recognised and "missing columns" in f.reason and "period" in f.reason and f.staging_table is None and r.status == "rejected"

def test_non_quarter_end_period_gives_a_warning(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ["AAAAAAAAAAAAAAAAAAAA,DE,202004,2020140,x,1,", "AAAAAAAAAAAAAAAAAAAA,DE,2020,2020140,x,1,"])
    f = run(db, [p]).files[0]; assert any("not a quarter end" in w for w in f.warnings) and any("not YYYYMM" in w for w in f.warnings)

def test_xlsx_data_file_gives_the_same_staging_as_csv(db):
    wb = Workbook(); ws = wb.active; ws.append(HEADER.strip().split(","))
    for r in ROWS: lei, nsa, per, item, lab, amt, _ = r.split(","); ws.append([lei, nsa, int(per), int(item), lab, float(amt), None])    # numbers stored as numbers
    x = db.dir / "tr_oth_x.xlsx"; wb.save(x)
    f = run(db, [str(x)]).files[0]
    assert f.recognised and f.encoding == "xlsx" and f.rows == 6 and f.aggregate_rows == 2
    assert [(p.year, p.quarter, p.banks, p.rows) for p in f.pairs] == [(2020, 1, 2, 2), (2020, 2, 2, 2)]
    db.cur.execute(f"SELECT period, item FROM staging.f{f.file_id} LIMIT 1"); assert db.cur.fetchone() == ("202003", "2020140")   # not 202003.0

def test_workbooks_are_checked_by_content(db):
    wb = Workbook(); wb.active.title = "Bank list"; wb.active.append(["LEI_Code", "Name"]); wb.save(db.dir / "TR_Metadata_x.xlsx")
    wb2 = Workbook(); wb2.active.append(["Dataset", "Item"]); wb2.save(db.dir / "SDD_x.xlsx"); bad = Workbook(); bad.active.append(["foo"]); bad.save(db.dir / "SDD_bad.xlsx")
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    r = run(db, [p, str(db.dir / "TR_Metadata_x.xlsx"), str(db.dir / "SDD_x.xlsx"), str(db.dir / "SDD_bad.xlsx")])
    ok = {f.name: f.recognised for f in r.files}; assert ok == {"tr_oth_x.csv": True, "TR_Metadata_x.xlsx": True, "SDD_x.xlsx": True, "SDD_bad.xlsx": False}

def test_a_corrupt_file_rolls_everything_back(db):
    good = write_csv(db.dir / "tr_oth_x.csv", ROWS); bad = write_csv(db.dir / "tr_cre_x.csv", ["AAAAAAAAAAAAAAAAAAAA,DE,202003,1,x,1,,EXTRA"])
    with pytest.raises(UnreadableFile, match="values, the header has"): run(db, [good, bad])
    assert count(db, "import_batch") == 0 and count(db, "source_file") == 0 and count(db, "audit_log") == 0
    db.cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'staging'"); assert db.cur.fetchone()[0] == 0   # no orphan staging table
    assert not [f for _, _, fs in os.walk(db.storage) for f in fs if f.endswith(".csv")]                                              # stored copies removed

def test_unknown_user_is_refused(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ROWS)
    with pytest.raises(Exception, match="does not exist"): run(db, [p], user_id=99)
    assert count(db, "import_batch") == 0

def test_blank_lines_and_short_rows_are_handled(db):
    p = write_csv(db.dir / "tr_oth_x.csv", ["AAAAAAAAAAAAAAAAAAAA,DE,202003,2020140,x,1", "", "BBBBBBBBBBBBBBBBBBBB,FR,202003,2020140,x,2,"])
    f = run(db, [p]).files[0]; assert f.rows == 2
