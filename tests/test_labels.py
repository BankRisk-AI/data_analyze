import pandas as pd
from te_engine.labels import e1_labels

def _p(rows):
    d = pd.DataFrame(rows, columns=["q", "cet1_ratio", "tier1_ratio", "total_capital_ratio"])
    d["lei"] = "A"; d["quarter"] = pd.PeriodIndex(d.pop("q"), freq="Q"); return d

def test_positive_and_censoring():
    ok = (0.12, 0.13, 0.15)
    p = _p([("2020Q1",) + ok, ("2020Q2",) + ok, ("2020Q3",) + ok, ("2020Q4", 0.06, 0.07, 0.09), ("2021Q1",) + ok])
    y = e1_labels(p).set_index("quarter")["y_e1"]
    assert y[pd.Period("2020Q1")] == 1.0          # breach at t+3
    assert pd.isna(y[pd.Period("2020Q4")])        # not compliant at t -> excluded
    assert pd.isna(y[pd.Period("2021Q1")])        # horizon not observed -> excluded

def test_negative_needs_full_horizon():
    ok = (0.12, 0.13, 0.15)
    p = _p([(f"{2020 + i // 4}Q{i % 4 + 1}",) + ok for i in range(6)])
    y = e1_labels(p).set_index("quarter")["y_e1"]
    assert y[pd.Period("2020Q1")] == 0.0 and y[pd.Period("2020Q2")] == 0.0
    assert pd.isna(y[pd.Period("2020Q3")])

def test_label_uses_only_future_window():
    ok = (0.12, 0.13, 0.15)
    a = _p([(f"{2020 + i // 4}Q{i % 4 + 1}",) + ok for i in range(6)])
    b = a.copy(); b.loc[0, "cet1_ratio"] = 0.12  # change only the observation at t
    assert e1_labels(a)["y_e1"].equals(e1_labels(b)["y_e1"])
