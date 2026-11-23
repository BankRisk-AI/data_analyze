TARGETS = ("T1", "T2", "T3", "T4", "T5", "T5_noT1")
GRIDS = ("semiannual", "quarterly")
ALGORITHMS = ("LR", "RF", "XGB")
FEATURE_SETS = ("robustness_v1", "full_v1")
THRESHOLDS = ("matched_far", "max_ur_0_9")
MAX_BUDGET = 60

FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
