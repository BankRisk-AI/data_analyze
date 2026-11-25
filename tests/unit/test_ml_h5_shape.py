"""Regression tests: H5 SHAP shape handling for LR with add_indicator=True.

Root cause: SimpleImputer(add_indicator=True) appends indicator columns per
feature with any NaN in that fold's training set. Different folds may have
different NaN-column counts, so SHAP matrices have unequal second dimensions.

T-2c fix: truncate to n_base.
T-2e fix: use get_feature_names_out() per fold to map SHAP to original feature
names by name, not position. This handles all-NaN columns that the imputer may
drop or reorder in some sklearn versions. Indicator columns are dropped.
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.impute import SimpleImputer


def test_shap_vstack_fails_without_truncation():
    """Reproduce the crash: np.vstack raises when SHAP arrays have different widths."""
    shap_fold1 = np.ones((5, 51))
    shap_fold2 = np.ones((3, 54))
    with pytest.raises(ValueError, match="dimensions"):
        np.vstack([shap_fold1, shap_fold2])


def test_shap_truncation_to_base_features_fixes_vstack():
    """Truncating to n_base columns resolves the mismatch."""
    n_base = 50
    shap_fold1 = np.ones((5, 51))
    shap_fold2 = np.ones((3, 54))
    result = np.vstack([arr[:, :n_base] for arr in [shap_fold1, shap_fold2]])
    assert result.shape == (8, n_base)


def test_get_feature_names_out_maps_shap_with_all_nan_column():
    """Name-based SHAP mapping correctly aligns when one fold has an all-NaN column.

    Scenario: 3 features ['a', 'b', 'c']; fold has column 'b' entirely NaN.
    The imputer with add_indicator=True still outputs all 3 features plus
    indicators. The name-based mapping must correctly assign SHAP[:, 0] to 'a',
    SHAP[:, 1] to 'b', SHAP[:, 2] to 'c' regardless of indicator count.
    """
    columns = ["a", "b", "c"]
    n_base = len(columns)
    col_to_idx = {col: j for j, col in enumerate(columns)}

    # Fold training data: column 'b' (index 1) is all NaN
    X_fold = np.array([[1.0, np.nan, 3.0],
                       [2.0, np.nan, 4.0],
                       [3.0, np.nan, 5.0]])
    imp = SimpleImputer(strategy="median", add_indicator=True)
    imp.fit(X_fold)

    names_out = imp.get_feature_names_out(np.asarray(columns))
    # sklearn DROPS all-NaN columns from the main output and adds only their
    # missingindicator; names_out is ['a', 'c', 'missingindicator_b'], not
    # ['a', 'b', 'c', 'missingindicator_b']. This proves positional slicing
    # [:, :n_base] misaligns SHAP: position 1 is 'c' not 'b'.
    assert "b" not in list(names_out), "all-NaN column 'b' must be dropped from main output"
    assert "missingindicator_b" in list(names_out), "indicator for 'b' must still be present"

    # Simulate SHAP values: (2 samples, len(names_out) features)
    n_shap_cols = len(names_out)
    sv_arr = np.arange(2 * n_shap_cols, dtype=float).reshape(2, n_shap_cols)

    aligned = np.zeros((sv_arr.shape[0], n_base))
    for i, name in enumerate(names_out):
        if i < sv_arr.shape[1] and name in col_to_idx:
            aligned[:, col_to_idx[name]] = sv_arr[:, i]

    # 'a' and 'c' are correctly placed; 'b' stays zero (dropped by imputer)
    names_list = list(names_out)
    np.testing.assert_array_equal(aligned[:, col_to_idx["a"]], sv_arr[:, names_list.index("a")])
    np.testing.assert_array_equal(aligned[:, col_to_idx["c"]], sv_arr[:, names_list.index("c")])
    np.testing.assert_array_equal(aligned[:, col_to_idx["b"]], np.zeros(2),
                                  err_msg="dropped column must map to zero SHAP")

    # Positional slicing [:, :n_base] would have put sv_arr[:,1] (='c') at position 1 ('b')
    wrong_aligned = sv_arr[:, :n_base]
    assert not np.array_equal(wrong_aligned[:, col_to_idx["b"]], np.zeros(2)), (
        "positional slicing incorrectly assigns c's SHAP to b's position")
