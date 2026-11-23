from pathlib import Path


def test_repository_test_storage_is_not_prepared_storage():
    root = Path(__file__).resolve().parents[2]
    prepared_storage = (root / "eba_prepared" / "storage").resolve()
    assert not prepared_storage.exists()


def test_fixture_storage_is_outside_prepared_data(tmp_path):
    root = Path(__file__).resolve().parents[2]
    assert (root / "eba_prepared").resolve() not in tmp_path.resolve().parents
