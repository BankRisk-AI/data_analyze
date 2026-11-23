"""Finding the staging table of a file: its columns, its metadata and all tables of an import."""
from __future__ import annotations

from dataclasses import dataclass

from psycopg2 import sql

from app.core.exceptions import InvalidParameter
from app.modules.eba_processing.domain.exceptions import DatasetNotFound, ImportNotFound
from app.shared.staging import STAGING_SCHEMA, staging_identifier, staging_table_name


@dataclass(frozen=True)
class Dataset:
    file_id: int
    import_id: int
    file_name: str
    file_type: str
    table: sql.Identifier
    columns: list[str]

    def col(self, name: str) -> sql.Identifier:
        if name not in self.columns:
            raise InvalidParameter(f"unknown column '{name}' for dataset {self.file_id}; available: {', '.join(self.columns)}")
        return sql.Identifier(name)


def import_exists(cur, import_id: int) -> bool:
    cur.execute("SELECT 1 FROM import_batch WHERE import_id = %s", (import_id,))
    return cur.fetchone() is not None


def _columns(cur, file_id: int) -> list[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (STAGING_SCHEMA, staging_table_name(file_id)))
    return [r[0] for r in cur.fetchall()]


def get_dataset(cur, file_id: int) -> Dataset:
    cur.execute("SELECT import_id, file_name, file_type FROM source_file WHERE file_id = %s", (file_id,))
    row = cur.fetchone()
    if row is None:
        raise DatasetNotFound(f"no file with id {file_id}")
    cols = _columns(cur, file_id)
    if not cols:
        raise DatasetNotFound(f"file {file_id} ({row[1]}) has no staging table: it was dropped, never loaded or is not a data file")
    return Dataset(file_id, row[0], row[1], row[2], staging_identifier(file_id), cols)


def list_datasets(cur, import_id: int) -> list[Dataset]:
    if not import_exists(cur, import_id):
        raise ImportNotFound(f"import {import_id} does not exist")
    cur.execute("SELECT file_id FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    out = []
    for (fid,) in cur.fetchall():
        try:
            out.append(get_dataset(cur, fid))
        except DatasetNotFound:
            continue
    return out
