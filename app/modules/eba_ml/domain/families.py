"""SHAP feature-family definitions (Table 3.x, H5).

Pure mapping — no IO, no DB.
"""
from __future__ import annotations

# Primary families: family name -> set of base feature names.
# Variants (_rank, _change12m, _missing) are grouped with their base feature.
FAMILIES: dict[str, set[str]] = {
    "Capital": {"cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"},
    "Asset quality": {"npl_ratio", "stage2_share"},
    "Earnings": {"roe_annualised"},
    "Concentration": {"nace_hhi", "sovereign_hhi"},
    "Growth": {"loan_growth_yoy"},
    "Liquidity": set(),
}

# Sensitivity grouping: maps primary families into 4 broad groups (§3.6, H5).
SENSITIVITY_GROUPS: dict[str, list[str]] = {
    "Capital": ["Capital"],
    "Earnings": ["Earnings"],
    "Asset quality": ["Asset quality", "Concentration", "Growth"],
    "Liquidity": ["Liquidity"],
}


def assign_family(base_feature: str) -> str:
    """Return the primary family name for a base feature name (H5).

    base_feature: feature name with _rank/_change12m/_missing stripped.
    Returns 'Liquidity' as default when no match found.
    """
    for name, members in FAMILIES.items():
        if base_feature in members:
            return name
    return "Liquidity"


def group_shap_values(shap_values: "np.ndarray", columns: list[str]) -> "dict[str, np.ndarray]":
    """Accumulate per-column SHAP values into primary family totals (H5).

    shap_values: shape (n_samples, n_columns).
    columns: feature names matching the second axis of shap_values.
    Returns {family_name: summed_shap_array}.
    """
    import numpy as np
    grouped: dict[str, np.ndarray] = {}
    for j, col in enumerate(columns):
        base = col.split("_rank")[0].split("_change12m")[0].split("_missing")[0]
        family = assign_family(base)
        if family not in grouped:
            grouped[family] = np.zeros(shap_values.shape[0])
        grouped[family] += shap_values[:, j]
    return grouped
