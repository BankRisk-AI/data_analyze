GRIDS = ("semiannual", "quarterly")
ALGORITHMS = ("LR", "RF", "XGB")
FEATURE_SETS = ("robustness_v1", "full_v1")
THRESHOLDS = ("operating_point_f2", "top_10pct_per_period")
LABEL_OPTIONS = ("E1", "E2", "E3", "E2_or_E3")
TAIL_QUANTILES = (0.90, 0.95, 0.975, 0.99)
MAX_BUDGET = 60

FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
