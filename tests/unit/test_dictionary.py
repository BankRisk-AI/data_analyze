from openpyxl import Workbook

from app.core.dictionary import _data_items, build_dictionary


def _sdd(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["title row"])
    ws.append(["Item", "Label", "Category", "Dataset", "Item_TR_2020S", "Item_TR_2020A"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_dictionary_builds_chains_and_is_idempotent(db, tmp_path):
    root = tmp_path / "prepared"
    (root / "2020S").mkdir(parents=True)
    (root / "2020A").mkdir(parents=True)
    _sdd(root / "2020S" / "SDD.xlsx", [["202001", "Ratio", "Capital", "tr_oth", "", ""]])
    _sdd(root / "2020A" / "SDD.xlsx", [["202002", "Ratio", "Capital", "tr_oth", "202001", ""]])
    first = build_dictionary(root, db.schema)
    second = build_dictionary(root, db.schema)
    assert first["sdd_direct"] >= 1
    assert second["ambiguous"] == 0
    db.cur.execute(
        "SELECT source_item, method FROM indicator_code_map WHERE edition_label='2020S' AND dataset='oth'"
    )
    assert db.cur.fetchone() == ("202001", "sdd_direct")


def test_data_only_items_count_non_aggregate_rows(tmp_path):
    root = tmp_path / "prepared"
    edition = root / "2016"
    edition.mkdir(parents=True)
    (edition / "tr_oth_2016.csv").write_text(
        "Item,Label,LEI_Code,NSA\n"
        "160001,Metric,XXXXXXXXXXXXXXXXXXXX,OT\n"
        "160001,Metric,LEI0000000000000001,DE\n"
        "160002,Other,LEI0000000000000002,FR\n",
        encoding="cp1252",
    )

    items, _ = _data_items(root)

    assert items[("2016", "oth", "160001")] == ("Metric", 1)
    assert items[("2016", "oth", "160002")] == ("Other", 1)


def test_2015_capital_ratios_follow_labeled_transitional_chain(db, tmp_path):
    root = tmp_path / "prepared"
    for edition in ("2015", "2020S", "2025"):
        (root / edition).mkdir(parents=True)

    def write(path, headers, rows):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)

    write(root / "2015" / "SDD.xlsx",
          ["Item", "Label", "Category", "Dataset"],
          [["150135", "Common Equity Tier 1 Capital ratio", "Capital", "tr_oth"],
           ["150136", "Tier 1 Capital ratio", "Capital", "tr_oth"],
           ["150137", "Total Capital ratio", "Capital", "tr_oth"]])
    write(root / "2020S" / "SDD.xlsx",
          ["Item", "Label", "Category", "Dataset", "Item_TR_2015"],
          [["2020140", "COMMON EQUITY TIER 1 CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "150135"],
           ["2020141", "TIER 1 CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "150136"],
           ["2020142", "TOTAL CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "150137"]])
    write(root / "2025" / "SDD.xlsx",
          ["Item", "Label", "Category", "Dataset", "Item_TR_2020S", "Item_TR_2015"],
          [["2520140", "COMMON EQUITY TIER 1 CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "2020140", "150135"],
           ["2520141", "TIER 1 CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "2020141", "150136"],
           ["2520142", "TOTAL CAPITAL RATIO (transitional period)", "Capital", "tr_oth", "2020142", "150137"]])

    build_dictionary(root, db.schema)
    db.cur.execute(
        """SELECT source_item, i.std_code
           FROM indicator_code_map m JOIN indicator i USING (indicator_id)
           WHERE edition_label='2015' AND dataset='oth'
           ORDER BY source_item"""
    )
    assert db.cur.fetchall() == [
        ("150135", "2520140"), ("150136", "2520141"), ("150137", "2520142")
    ]
