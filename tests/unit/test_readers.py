from app.modules.eba_ingest.infrastructure.readers.readers import csv_rows


def test_csv_reader_restores_known_scientific_lei(tmp_path):
    path = tmp_path / "tr_sov.csv"
    path.write_text("LEI_Code,NSA\n9.598E+19,ES\n", encoding="cp1252")

    assert list(csv_rows(str(path), "cp1252")) == [
        ["LEI_Code", "NSA"],
        ["95980020140005881190", "ES"],
    ]
