# Session: Test refactoring — 2026-11-23

## Goal
Reorganize tests into unit/, integration/, data_processing/ categories.

## Changes
- Created `tests/unit/` (16 files), `tests/integration/` (14 files + helpers.py), `tests/data_processing/` (2 files).
- Removed old `tests/architecture/`, `tests/core/`, `tests/processing/` and top-level test files.
- Fixed `Path(__file__).resolve().parents[N]` depth in 4 files:
  - `unit/test_memory_validation.py`, `unit/test_openapi.py`, `unit/test_storage_hygiene.py`: 1→2
  - `unit/architecture/test_layering.py`: 2→3
- Added `pytest.mark.data_processing` to both data_processing test files.
- Updated `pytest.ini`: added `not data_processing` to addopts, `data_processing` marker, `pythonpath = tests`.
- Updated `.github/workflows/test.yaml`: `pytest tests/unit/ tests/integration/ -v`.

## Verification
- `pytest tests/unit/` → 65 passed
- `pytest tests/integration/` → 117 passed, 1 deselected (slow)
- `pytest tests/` → 182 collected, 4 deselected (3 data_processing + 1 slow)
- `pytest tests/data_processing/ --collect-only` → 0 collected (addopts excludes)
- `pytest tests/data_processing/ -m "data_processing" --collect-only` → 3 collected

## Amendment (same session)
- Moved `tests/unit/test_dimensions.py` → `tests/data_processing/test_dimensions.py`.
  - `test_build_dimensions_decodes_country_and_nace` reads `eba_prepared/2020A/TR_Metadata.xlsx`; protected by `@pytest.mark.skipif`.
  - `test_build_dimensions_marks_missing_metadata_undecoded` moved with the file (pure unit logic, no real file dependency).
  - Both tests get `pytestmark = pytest.mark.data_processing`.
- Updated unit count: 65 → 63; data_processing count: 3 → 5.

## Remaining work
None for this task.
