# Data inventory

## Edition 2020

- `oth` (tr_oth_2.csv): 53,104 rows, encoding cp1252, 135 banks, periods ['202003', '202006'], 163 items; aggregate rows dropped: 422
- `cre` (tr_cre_2.csv): 392,278 rows, encoding cp1252, 135 banks, periods ['202003', '202006'], 94 items; aggregate rows dropped: 3954
- `mrk` (tr_mrk_2.csv): 13,566 rows, encoding cp1252, 135 banks, periods ['202003', '202006'], 25 items; aggregate rows dropped: 102
- `sov`: file not found
- LEI coverage vs tr_oth: oth: 135/135, cre: 135/135, mrk: 135/135
- banks per period (tr_oth): 202003: 131, 202006: 135
- banks present in only one period: 4
- bank country codes: 27 (True contains GB)
- `oth` dimension columns: ['assets_fv', 'assets_stages', 'exposure', 'financial_instruments', 'fin_end_year', 'n_quarters']
- `cre` dimension columns: ['portfolio', 'country', 'country_rank', 'exposure', 'status', 'perf_status', 'nace_codes']
