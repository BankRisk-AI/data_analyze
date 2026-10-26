# te_engine: preparation of EBA Transparency Exercise data

Built and tested on the 2020 edition files (tr_oth, tr_cre, tr_mrk, SDD, TR_Metadata). tr_sov was not available.

## Run
```
pip install -r requirements.txt
mkdir -p data/TE2020 && cp tr_*.csv SDD*.xlsx TR_Metadata*.xlsx data/TE2020/
python -m te_engine.cli --edition data/TE2020 --out reports
# several editions, oldest to newest:
python -m te_engine.cli --edition data/TE2019 --edition data/TE2020 --edition data/TE2021 --out reports
pytest
```
Outputs: reports/data_inventory.md, reports/quality_report.md, reports/panel.csv.

## What it does
1. Reads the CSV files (cp1252 fallback), drops the "All other banks" aggregate (LEI of X characters / country OT).
2. Resolves item codes per edition through the SDD crosswalk (codes change between editions), falls back to an exact label match, and verifies every label before using an item.
3. Maps old LEIs to current LEIs (Bank list sheet) and stacks editions into a bank x quarter panel (latest edition wins on duplicates).
4. Derives: npl_ratio, stage2_share, roe_annualised (year-to-date profit annualised with n_quarters), nace_hhi, trends (only from an existing previous quarter).
5. Quality checks (identities, units, missingness, outliers, panel balance) and the E1 event report with the STOP/GO rule.

## Known limits
- sovereign_hhi needs tr_sov (not provided yet): set SOVEREIGN_ITEM in config.py after inspecting the file.
- LCR is not present in the 2020 edition's tr_oth items.
- Amount units are not stated in the files provided (probably million EUR): check the guide of each edition.
- Only two quarters per edition in 2020: yoy trends and 4-quarter labels need several editions stacked.
