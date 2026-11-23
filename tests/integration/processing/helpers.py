"""Synthetic staged datasets for the processing tests: the data are generated, so every expected number can be computed by hand."""
from __future__ import annotations

from app.modules.eba_ingest import ingest

HEADER = "LEI_Code,NSA,Period,Item,Label,Portfolio,Amount,footnote\n"


def lei(i: int) -> str:
    return f"LEI{i:017d}"                     # 20 alphanumeric characters


def banks(n: int = 40, periods=("202003", "202006"), country: str = "DE") -> list[str]:
    """I1 = 10 + 0.5 i, I2 = 2 * I1 + 1 (perfectly correlated), for n banks and every period; portfolio 0."""
    rows = []
    for p in periods:
        for i in range(n):
            x = 10 + i * 0.5
            rows.append(f"{lei(i)},{country},{p},I1,Item one,0,{x},")
            rows.append(f"{lei(i)},{country},{p},I2,Item two,0,{2 * x + 1},")
    return rows


def stage(db, rows: list[str], name: str = "tr_cre_t.csv", header: str = HEADER) -> tuple[int, int]:
    """Writes the CSV, ingests it (synchronously) and returns (import_id, file_id) of the staged file."""
    path = db.dir / name
    path.write_text(header + "\n".join(rows) + "\n", encoding="cp1252")
    report = ingest([str(path)], db.storage, schema=db.schema)
    return report.import_id, report.files[0].file_id
