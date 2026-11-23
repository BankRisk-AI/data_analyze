import csv

from app.core.smoke import build_sample


def test_build_sample_preserves_header_encoding_and_filters_rows(tmp_path):
    source = tmp_path / "source" / "2020"
    source.mkdir(parents=True)
    (source / "SDD.xlsx").write_bytes(b"placeholder")
    csv_path = source / "tr_oth.csv"
    with csv_path.open("w", encoding="cp1252", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["LEI_Code", "Period", "Label"])
        writer.writerow(["0W2PZJM8XOY22M4GG883", "201912", "keep"])
        writer.writerow(["xxxxxxxxxxxxxxxxxxxx", "201912", "aggregate"])
        writer.writerow(["OTHER", "201912", "drop"])

    target = build_sample(tmp_path / "source", tmp_path / "sample")
    output = target / "2020" / "tr_oth.csv"
    assert output.read_bytes().lstrip(b"\xef\xbb\xbf").startswith(b"LEI_Code;")
    with output.open(encoding="cp1252", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    assert [row["Label"] for row in rows] == ["keep", "aggregate"]
