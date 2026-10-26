"""Feature specification, expressed with item codes of the 2020 edition (verified on the 2020 files).
Item codes change between editions (the first two digits encode the edition); the SDD crosswalk is used
to resolve them (see items.py)."""
ALERT_LEVELS = {"cet1_ratio": 0.07, "tier1_ratio": 0.085, "total_capital_ratio": 0.105}  # ratios are stored as FRACTIONS
HORIZON = 4
ZERO_DIMS_OTH = {"ASSETS_FV": "0", "ASSETS_Stages": "0", "Exposure": "0", "Financial_instruments": "0"}
ZERO_DIMS_CRE = {"Portfolio": "0", "Country": "0", "Country_rank": "0", "Exposure": "0", "Status": "0", "NACE_codes": "0"}

# name -> (dataset, base item code, extra filters)
SIMPLE = {
    "cet1_capital": ("oth", "2020102", {}), "at1_capital": ("oth", "2020128", {}),
    "tier1_capital": ("oth", "2020133", {}), "tier2_capital": ("oth", "2020134", {}),
    "rwa": ("oth", "2020138", {}),
    "cet1_ratio": ("oth", "2020140", {}), "tier1_ratio": ("oth", "2020141", {}),
    "total_capital_ratio": ("oth", "2020142", {}), "cet1_ratio_fully_loaded": ("oth", "2020146", {}),
    "leverage_ratio": ("oth", "2020905", {}), "leverage_exposure": ("oth", "2020903", {}),
    "total_assets": ("oth", "2021010", {}), "total_equity": ("oth", "2021216", {}),
    "net_profit_ytd": ("oth", "2020335", {}),
    "loans_gross": ("cre", "2020603", {"Perf_Status": "0"}),
    "npl_gross": ("cre", "2020603", {"Perf_Status": "2"}),
    "npe_stage3": ("cre", "2020603", {"Perf_Status": "23"}),
}
NACE_ITEM = ("cre", "2021301")          # gross carrying amount of loans to NFCs, by NACE (Perf_Status 0 = total)
SOVEREIGN_ITEM = None                    # to be set after inspecting tr_sov / SDD (not available in the 2020 upload)
FAMILIES = {"capital": ["cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"],
            "asset_quality": ["npl_ratio", "npl_delta_qoq", "loan_growth_qoq", "loan_growth_yoy"],
            "earnings": ["roe_annualised"], "concentration": ["nace_hhi", "sovereign_hhi"]}

# expected labels (2020 edition) used to VERIFY every resolved item and as a fallback when the SDD lacks the item
LABELS = {
    "2020102": "COMMON EQUITY TIER 1 CAPITAL (net of deductions and after applying transitional adjustments)",
    "2020128": "ADDITIONAL TIER 1 CAPITAL (net of deductions and after transitional adjustments)",
    "2020133": "TIER 1 CAPITAL (net of deductions and after transitional adjustments)",
    "2020134": "TIER 2 CAPITAL (net of deductions and after transitional adjustments)",
    "2020138": "TOTAL RISK EXPOSURE AMOUNT", "2020140": "COMMON EQUITY TIER 1 CAPITAL RATIO (transitional period)",
    "2020141": "TIER 1 CAPITAL RATIO (transitional period)", "2020142": "TOTAL CAPITAL RATIO (transitional period)",
    "2020146": "COMMON EQUITY TIER 1 CAPITAL RATIO (fully loaded)",
    "2020905": "Leverage ratio - using a transitional definition of Tier 1 capital",
    "2020903": "Total leverage ratio exposures - using a transitional definition of Tier 1 capital",
    "2021010": "Total Assets", "2021216": "TOTAL EQUITY", "2020335": "PROFIT OR (-) LOSS FOR THE YEAR",
    "2020603": "Gross carrying amount on Loans and advances (including at amortised cost and fair value)",
    "2021301": "Gross carrying amount",
    "2021019": "Gross carrying amount: Financial assets at amortised cost, Loans and advances",
}
