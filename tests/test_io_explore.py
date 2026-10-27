import pandas as pd
from te_engine.discover import find_year_folders
from te_engine.io import read_data_file, is_aggregate
from te_engine import explore

COLS = ["LEI_Code", "NSA", "Period", "Item", "Label", "Amount"]
ROWS = [["A" * 20, "DE", "202003", "2020140", "CET1 ratio", "0.15"], ["B" * 20, "FR", "202003", "2020140", "CET1 ratio", "0.12"],
        ["X" * 20, "OT", "202003", "2020140", "CET1 ratio", "0.5"], ["A" * 20, "DE", "202006", "2020140", "CET1 ratio – new", "0.16"]]

def test_year_folders_are_discovered(tmp_path):
    for n in ("year_2019", "year_2020", "notes", "year_20"): (tmp_path / n).mkdir()
    assert list(find_year_folders(str(tmp_path))) == [2019, 2020]

def test_csv_cp1252_and_xlsx_give_same_frame(tmp_path):
    df = pd.DataFrame(ROWS, columns=COLS)
    df.to_csv(tmp_path / "tr_oth_x.csv", index=False, encoding="cp1252"); df.to_excel(tmp_path / "tr_oth_x.xlsx", index=False)
    a, b = read_data_file(str(tmp_path / "tr_oth_x.csv")), read_data_file(str(tmp_path / "tr_oth_x.xlsx"))
    assert a.attrs["encoding"] == "cp1252" and b.attrs["encoding"] == "xlsx"
    assert a[["lei", "period", "item", "amount"]].astype(str).equals(b[["lei", "period", "item", "amount"]].astype(str))
    assert is_aggregate(a).sum() == 1

def _long():
    d = pd.DataFrame(ROWS, columns=["lei", "country_bank", "period", "item_std", "label", "amount"]); d["amount"] = d["amount"].astype(float)
    d["year"] = 2020; return d

def test_filter_aggregate_pivot():
    d = _long()
    f = explore.filter_long(d, countries=["DE", "FR"], item_std=["2020140"])
    assert len(f) == 3
    a = explore.aggregate_long(f, ["country_bank"], "mean").set_index("country_bank")["mean_amount"]
    assert abs(a["DE"] - 0.155) < 1e-12 and a["FR"] == 0.12
    p = explore.pivot_long(f, ["country_bank"], ["period"], "sum")
    assert p.loc["DE", "202006"] == 0.16
    assert explore.filter_long(d, label_contains="new").shape[0] == 1
