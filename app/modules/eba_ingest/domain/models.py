from dataclasses import asdict, dataclass, field

from .constants import DATA_TYPES


@dataclass
class PairReport:
    year: int
    quarter: int
    banks: int
    rows: int


@dataclass
class FileReport:
    name: str
    size_bytes: int
    sha256: str
    file_type: str
    recognised: bool
    encoding: str

    rows: int | None = None
    aggregate_rows: int | None = None
    normalised_amounts: int = 0
    columns: list[str] | None = None

    reason: str | None = None
    staging_table: str | None = None
    file_id: int | None = None
    seconds: float = 0.0

    pairs: list[PairReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestReport:
    import_id: int
    status: str
    files: list[FileReport]

    seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def data_files(self) -> list[FileReport]:
        return [f for f in self.files if f.recognised and f.file_type in DATA_TYPES]
