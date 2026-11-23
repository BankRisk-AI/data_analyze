"""Reading the registered files: content checks, loading into staging tables and the report of the import.
`process_import` is what the worker runs; `ingest` is the synchronous all-or-nothing path used by the command line."""
from __future__ import annotations

import time
import re
from dataclasses import dataclass

from app.core.config import get_schema
from app.core.database import connect
from app.core.logging import get_logger
from app.modules.eba_ingest.application.upload_service import (
    DEFAULT_MAX_BYTES,
    check_before_registering,
    register_files,
    remove_files,
    store_files,
)
from app.modules.eba_ingest.domain import IngestError, UnreadableFile
from app.modules.eba_ingest.domain.constants import DATA_TYPES
from app.modules.eba_ingest.domain.models import FileReport, IngestReport
from app.modules.eba_ingest.domain.services.file_detector import classify_name, missing_required, normalise_header
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.modules.eba_ingest.infrastructure.readers import readers
from app.modules.eba_ingest.infrastructure.staging import staging
from app.modules.eba_ingest.infrastructure.staging.period_report import fill_period_report
from app.shared.staging import staging_identifier, staging_qualified

Emit = "callable[[str, int], None]"
logger = get_logger(__name__)
_GROUPED_AMOUNT = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


@dataclass
class Inspection:
    report: FileReport
    rows: object = None          # iterator of rows (header already consumed) when the file is a recognised data file
    columns: list[str] | None = None

    @property
    def is_data(self) -> bool:
        return self.rows is not None


def inspect_file(f: repo.SourceFileRow) -> Inspection:
    """Checks the content of one registered file. Raises UnreadableFile for an empty file or a bad header."""
    name, ftype = f.name, classify_name(f.name)
    low = name.lower()
    is_csv, is_xlsx = low.endswith(".csv"), low.endswith(".xlsx")
    rep = FileReport(name=name, size_bytes=f.size_bytes, sha256=f.sha256, file_type=ftype or "unrecognised", recognised=False,
                     encoding="xlsx" if is_xlsx else f.encoding, file_id=f.file_id)
    if ftype is None:
        rep.reason = "the name does not start with tr_oth, tr_cre, tr_mrk, tr_sov, SDD or TR_Metadata"
    elif not (is_csv or is_xlsx):
        rep.reason = "only .csv and .xlsx files are accepted"
    elif ftype in DATA_TYPES:
        rows = readers.csv_rows(f.stored_path, f.encoding) if is_csv else readers.xlsx_rows(f.stored_path)
        header = next(rows, None)
        if header is None:
            raise UnreadableFile(f"{name} is empty")
        try:
            cols = normalise_header(header)
        except ValueError as e:
            raise UnreadableFile(f"{name}: {e}") from e
        rep.columns = cols
        missing = missing_required(cols)
        if missing:
            rep.reason = "missing columns: " + ", ".join(missing)
        else:
            rep.recognised = True
            return Inspection(rep, rows, cols)
    else:                                                                       # SDD or TR_Metadata workbooks
        if not is_xlsx:
            rep.reason = f"{ftype} must be an .xlsx workbook"
        elif ftype == "TR_Metadata":
            rep.recognised = readers.xlsx_bank_list_sheet(f.stored_path) is not None
            rep.reason = None if rep.recognised else "no worksheet has a header containing 'LEI_code'"
        else:
            header = readers.xlsx_header(f.stored_path)
            rep.recognised = "Item" in header and "Dataset" in header
            rep.reason = None if rep.recognised else "the first row has no 'Item' and 'Dataset' columns"
    return Inspection(rep)


def stage_file(cur, insp: Inspection) -> None:
    started = time.perf_counter()
    rep = insp.report
    columns = list(insp.columns or [])
    rows = insp.rows
    if "label" not in columns:
        label_at = columns.index("amount") if "amount" in columns else len(columns)
        columns.insert(label_at, "label")
        rows = (list(row[:label_at]) + [""] + list(row[label_at:]) for row in rows)
    if "amount" in columns:
        amount_at = columns.index("amount")
        normalised = 0
        def normalise_amount(row):
            nonlocal normalised
            row = list(row)
            if amount_at >= len(row):
                return row
            value = str(row[amount_at] or "").strip()
            if _GROUPED_AMOUNT.fullmatch(value):
                row[amount_at] = value.replace(",", "")
                normalised += 1
            return row
        rows = (normalise_amount(row) for row in rows)
    t_copy = time.perf_counter()
    rep.rows = staging.create_and_copy(cur, rep.file_id, columns, rows, rep.name)
    t_fill = time.perf_counter()
    rep.normalised_amounts = normalised if "amount" in columns else 0
    rep.staging_table = staging_qualified(rep.file_id)
    fill_period_report(cur, staging_identifier(rep.file_id), rep)
    t_done = time.perf_counter()
    rep.seconds = round(t_done - started, 2)
    logger.info(
        "stage %s: total=%.2fs copy=%.2fs (%d rows) fill=%.2fs",
        rep.name, rep.seconds, t_fill - t_copy, rep.rows, t_done - t_fill,
    )


def _process(cur, import_id: int, files: list[repo.SourceFileRow], emit, job_id: int | None, user_id: int | None, t0: float) -> IngestReport:
    reports: list[FileReport] = []
    span = 90 / max(len(files), 1)
    for i, f in enumerate(files):
        base = 5 + int(span * i)
        emit(f"inspecting {f.name}", base)
        t_inspect = time.perf_counter()
        insp = inspect_file(f)
        logger.info("inspect %s: %.2fs", f.name, time.perf_counter() - t_inspect)
        if insp.is_data:
            emit(f"staging {f.name}", base + int(span * 0.2))
            stage_file(cur, insp)
        reports.append(insp.report)
    ok = any(r.recognised and r.file_type in DATA_TYPES for r in reports)
    report = IngestReport(import_id=import_id, status="uploaded" if ok else "rejected", files=reports)
    if not ok:
        report.error = "no recognised EBA data file (tr_oth, tr_cre, tr_mrk, tr_sov) was found"
        repo.set_import_status(cur, import_id, "rejected")
    emit("saving the report", 98)         # BEFORE finish_job: that UPDATE locks the job row, and progress updates use other connections
    repo.finish_job(cur, import_id, job_id, ok, report.error)
    report.seconds = round(time.perf_counter() - t0, 2)
    logger.info(
        "process total: %.2fs — %s",
        report.seconds,
        ", ".join(f"{r.name}={r.seconds}s" for r in reports if r.seconds > 0),
    )
    repo.save_report(cur, import_id, report.to_dict())
    repo.add_audit(cur, user_id, "import created", "import_batch", str(import_id), {"files": [r.name for r in reports]})
    return report


def process_import(import_id: int, schema: str | None = None, emit=None, job_id: int | None = None) -> IngestReport:
    """Worker path: reads the files already registered for the import (they are NOT stored or hashed again)."""
    t0 = time.perf_counter()
    logger.info("import processing started import_id=%s job_id=%s", import_id, job_id)
    emit = emit or (lambda message, percent: None)
    conn = connect(schema or get_schema())
    try:
        cur = conn.cursor()
        files = repo.source_files(cur, import_id)
        if not files:
            raise IngestError(f"import {import_id} has no source files")
        report = _process(cur, import_id, files, emit, job_id, repo.import_owner(cur, import_id), t0)
        conn.commit()
        logger.info("import processing completed import_id=%s duration_ms=%.2f", import_id, (time.perf_counter() - t0) * 1000)
        return report
    except Exception:
        logger.exception("import processing failed import_id=%s job_id=%s", import_id, job_id)
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest(paths, storage_dir: str, user_id: int | None = None, edition_label: str | None = None,
           max_bytes: int = DEFAULT_MAX_BYTES, schema: str = "public", progress=None) -> IngestReport:
    """Synchronous, all-or-nothing: stores, registers and stages in ONE transaction. On any error nothing is left behind
    (the stored copies created by this call are removed too). Raises FileTooLarge, DuplicateFile or UnreadableFile."""
    t0 = time.perf_counter()
    say = progress or (lambda message: None)
    t_store = time.perf_counter()
    stored, created_now = store_files(paths, storage_dir, max_bytes, say)
    logger.info("store_files: %.2fs for %d file(s)", time.perf_counter() - t_store, len(stored))
    conn = None
    try:
        conn = connect(schema)
        cur = conn.cursor()
        check_before_registering(cur, stored, user_id)
        import_id = repo.create_import(cur, user_id, edition_label)
        register_files(cur, import_id, stored)
        files = repo.source_files(cur, import_id)
        report = _process(cur, import_id, files, lambda message, percent: say(message), None, user_id, t0)
        conn.commit()
        return report
    except Exception:
        if conn:
            conn.rollback()
        remove_files(created_now)
        raise
    finally:
        if conn:
            conn.close()
