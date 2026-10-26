import pandas as pd, numpy as np
from te_engine.io import is_aggregate

def test_aggregate_bucket_detected():
    df = pd.DataFrame({"lei": ["XXXXXXXXXXXXXXXXXXXX", "xxxxxxxxxxxxxxxxxxxx", "0W2PZJM8XOY22M4GG883"], "country_bank": ["OT", "OT", "DE"]})
    assert is_aggregate(df).tolist() == [True, True, False]
