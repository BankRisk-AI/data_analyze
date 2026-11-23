QUERY_TIMEOUT_SECONDS = 10

FEATURES = {
    "cet1_ratio": ("CET1 ratio", "end-period CET1 ratio", "ratio", "201412", "higher_is_riskier"),
    "tier1_ratio": ("Tier 1 ratio", "end-period Tier 1 ratio", "ratio", "201412", "higher_is_riskier"),
    "total_capital_ratio": ("Total capital ratio", "end-period total capital ratio", "ratio", "201412", "higher_is_riskier"),
    "leverage_ratio": ("Leverage ratio", "reported transitional leverage ratio", "ratio", "201412", "lower_is_riskier"),
    "npl_ratio": ("NPL ratio", "non-performing loans divided by total loans", "ratio", "201412", "higher_is_riskier"),
    "stage2_share": ("Stage 2 share", "Stage 2 loans divided by Stage 1-3 loans", "ratio", "201809", "higher_is_riskier"),
    "roe_annualised": ("RoCET1", "annualised YTD profit divided by end-period CET1", "ratio", "201412", "both_extremes"),
    "loan_growth_qoq": ("Loan growth QoQ", "total loans divided by the prior calendar quarter minus one", "ratio", "201812", "both_extremes"),
    "loan_growth_yoy": ("Loan growth YoY", "total loans divided by the same month in the prior year minus one", "ratio", "201512", "both_extremes"),
    "nace_hhi": ("NACE HHI", "sum of squared NACE sector loan shares", "index", "201909", "higher_is_riskier"),
    "sovereign_hhi": ("Sovereign HHI", "sum of squared sovereign country shares", "index", "201412", "higher_is_riskier"),
}

FLAG_DESCRIPTIONS = {
    "missing_in_source": "Source value is absent.",
    "invalid_denominator": "A required denominator is non-positive or absent.",
    "template_gap": "The reporting template does not provide the feature.",
    "not_reported_this_period": "The source does not report this feature in this period.",
    "no_prior_period": "The required calendar comparison period is absent.",
    "implausible_value": "The raw value fails a source consistency check.",
    "specialist_institution": "The bank is in the version-controlled specialist list.",
    "outlier": "The value is outside the per-period robust MAD threshold.",
}
