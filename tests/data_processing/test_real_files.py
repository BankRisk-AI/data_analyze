"""Integration test on the prepared 2020A EBA files."""
import os, time, pytest
from app.modules.eba_ingest import ingest
from app.modules.eba_ingest.application.load_service import run_load
from app.modules.eba_processing.application.validation import run_validation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REAL = Path(os.getenv("EBA_REAL_DIR") or str(PROJECT_ROOT / "eba_prepared")) / "2020A"

FILES = ["tr_oth.csv", "tr_cre.csv", "tr_mrk.csv", "SDD.xlsx", "TR_Metadata.xlsx"]
pytestmark = [
    pytest.mark.data_processing,
    pytest.mark.skipif(not REAL.is_dir(), reason="EBA_REAL_DIR prepared layout not found"),
]


def test_original_2020_files_exist():
    missing = [
        filename
        for filename in FILES
        if not (REAL / filename).is_file()
    ]

    assert not missing, (
        f"Missing prepared 2020A files in {REAL}: {missing}"
    )


@pytest.mark.slow
def test_original_2020_files(db):
    started = time.perf_counter()
    r = ingest([os.path.join(REAL, f) for f in FILES], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    stage_seconds = time.perf_counter() - started
    assert r.status == "uploaded" and all(f.recognised for f in r.files)
    by = {f.file_type: f for f in r.files}
    assert {k: by[k].encoding for k in ("tr_oth", "tr_cre", "tr_mrk")} == {"tr_oth": "cp1252", "tr_cre": "cp1252", "tr_mrk": "cp1252"}   # the files are not UTF-8
    assert by["tr_cre"].rows == 396232 and by["tr_cre"].aggregate_rows == 3954 and by["tr_oth"].aggregate_rows == 422 and by["tr_mrk"].aggregate_rows == 102
    assert by["tr_oth"].rows - by["tr_oth"].aggregate_rows == 53104 and by["tr_mrk"].rows - by["tr_mrk"].aggregate_rows == 13566 and by["tr_cre"].rows - by["tr_cre"].aggregate_rows == 392278
    assert [(p.year, p.quarter, p.banks) for p in by["tr_oth"].pairs] == [(2020, 1, 131), (2020, 2, 135)]
    assert [(p.rows) for p in by["tr_cre"].pairs] == [182195, 210083]
    db.cur.execute("SELECT count(*) FROM source_file WHERE length(sha256) = 64 AND stored_path IS NOT NULL"); assert db.cur.fetchone()[0] == 5
    assert stage_seconds <= 60

    started = time.perf_counter()
    validation = run_validation(r.import_id, db.schema)
    validation_seconds = time.perf_counter() - started
    assert validation.can_proceed and validation_seconds <= 90

    started = time.perf_counter()
    run_load(r.import_id, db.schema)
    load_seconds = time.perf_counter() - started
    assert load_seconds <= 120
