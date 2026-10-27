"""Entry point of the application:   streamlit run app.py
Reads the ORIGINAL EBA files from data/year_YYYY/ (tr_oth*, tr_cre*, tr_mrk*, tr_sov* as .csv or .xlsx, SDD*.xlsx, TR_Metadata*.xlsx)."""
from __future__ import annotations
import io, json
import pandas as pd
import streamlit as st
from te_engine.workspace import Workspace
from te_engine import explore, charts, indicators, config as C
from te_engine.quality import panel_checks, missingness, iqr_flags
from te_engine.labels import e1_labels, event_report

st.set_page_config(page_title="EBA Transparency Exercise: data explorer", layout="wide")

@st.cache_resource(show_spinner=False)
def get_ws(root: str) -> Workspace:
    return Workspace(root)

@st.cache_data(show_spinner="Building the panel ...")
def get_panel(root: str, years: tuple) -> tuple[pd.DataFrame, list]:
    log: list = []
    return get_ws(root).panel(list(years), log), log

@st.cache_data(show_spinner="Loading the long table ...")
def get_long(root: str, dataset: str, years: tuple) -> pd.DataFrame:
    return get_ws(root).long(dataset, list(years))

def download(df: pd.DataFrame, name: str, key: str):
    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name=name, mime="text/csv", key=key)

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Data")
root = st.sidebar.text_input("Data folder", "data", help="Folder that contains year_2019, year_2020, ...")
if st.sidebar.button("Reload files"):
    st.cache_data.clear(); st.cache_resource.clear()
ws = get_ws(root)
if not ws.years:
    st.error(f"No folder named year_YYYY found in '{root}'. Expected: {root}/year_2020/tr_oth*.csv, tr_cre*.csv, tr_mrk*.csv, SDD*.xlsx, TR_Metadata*.xlsx")
    st.stop()
years = tuple(st.sidebar.multiselect("Years", ws.years, default=ws.years))
if not years:
    st.warning("Select at least one year."); st.stop()
panel, log = get_panel(root, years)
names = panel[["lei", "bank_name"]].drop_duplicates("lei").assign(label=lambda d: d["bank_name"].fillna(d["lei"]) + " (" + d["lei"].str[:6] + ")")
st.sidebar.caption(f"{panel['lei'].nunique()} banks, {panel['quarter'].nunique()} quarters, {len(panel)} bank-quarters")

st.title("EBA Transparency Exercise: data explorer")
tabs = st.tabs(["Overview", "Panel", "Explorer (original files)", "Charts", "Events", "Indicators"])

# ------------------------------------------------------------------ overview
with tabs[0]:
    st.subheader("Files found")
    st.dataframe(pd.DataFrame(ws.reports()).T.drop(columns=["missing_required"]).assign(missing=lambda d: [", ".join(ws.reports()[y]["missing_required"]) for y in d.index]), width="stretch")
    st.subheader("Quality checks")
    st.dataframe(panel_checks(panel), width="stretch", hide_index=True)
    st.subheader("Missing values")
    st.dataframe(missingness(panel).round(3), width="stretch")
    with st.expander("Decision log"):
        st.write("\n".join(f"- {l}" for l in log) or "nothing to report")
    with st.expander("Outlier flags (cross-sectional, IQR x 3)"):
        st.dataframe(iqr_flags(panel), width="stretch", hide_index=True)

# ------------------------------------------------------------------ panel
with tabs[1]:
    c1, c2, c3 = st.columns(3)
    qs = c1.multiselect("Quarters", sorted(map(str, panel["quarter"].unique())))
    cs = c2.multiselect("Countries", sorted(panel["country_bank"].dropna().unique()))
    bs = c3.multiselect("Banks", names["label"].tolist())
    d = panel.copy()
    if qs: d = d[d["quarter"].astype(str).isin(qs)]
    if cs: d = d[d["country_bank"].isin(cs)]
    if bs: d = d[d["lei"].isin(names[names["label"].isin(bs)]["lei"])]
    default_cols = ["lei", "bank_name", "country_bank", "quarter", "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio", "npl_ratio", "roe_annualised", "nace_hhi"]
    cols = st.multiselect("Columns", list(panel.columns), default=[c for c in default_cols if c in panel.columns])
    d = d.assign(quarter=d["quarter"].astype(str))
    st.dataframe(d[cols], width="stretch", hide_index=True); download(d[cols], "panel_selection.csv", "dl_panel")
    st.subheader("Aggregate the panel")
    a1, a2, a3 = st.columns(3)
    by = a1.multiselect("Group by", ["quarter", "year", "country_bank", "edition"], default=["quarter"])
    inds = a2.multiselect("Indicators", [c for c in panel.select_dtypes("number").columns if c != "year"], default=["cet1_ratio", "npl_ratio"])
    fn = a3.selectbox("Function", ["median", "mean", "min", "max", "count", "sum"])
    if inds:
        agg = d.groupby(by)[inds].agg(fn).reset_index() if by else d[inds].agg(fn).to_frame(fn).T
        st.dataframe(agg, width="stretch", hide_index=True); download(agg, "panel_aggregate.csv", "dl_agg")

# ------------------------------------------------------------------ explorer
with tabs[2]:
    st.caption("Works directly on the original long-format files. item_std = item code of the 2020 edition, so the same indicator can be aggregated across years.")
    ds = st.selectbox("File", ["oth", "cre", "mrk", "sov"], format_func=lambda k: {"oth": "tr_oth (capital, leverage, RWA, P&L, assets, liabilities)", "cre": "tr_cre (credit risk, NPE, NACE)", "mrk": "tr_mrk (market risk)", "sov": "tr_sov (sovereign)"}[k])
    long = get_long(root, ds, years)
    if long.empty:
        st.info(f"No data for {ds} in the selected years (file missing).")
    else:
        cat = explore.catalog_items(long)
        f1, f2, f3 = st.columns(3)
        sel_periods = f1.multiselect("Periods", sorted(long["period"].unique()))
        sel_countries = f2.multiselect("Bank countries", sorted(long["country_bank"].dropna().unique()), key="exp_c")
        text = f3.text_input("Label contains", "")
        sel_items = st.multiselect("Items (search by code or label)", (cat["item_std"] + " | " + cat["label"].str.slice(0, 90)).tolist())
        dims = {}
        with st.expander("Dimension filters"):
            for col in explore.DIM_COLS.get(ds, []):
                if col in long.columns:
                    vals = st.multiselect(col, sorted(long[col].dropna().unique()), key=f"dim_{col}")
                    if vals: dims[col] = vals
        sub = explore.filter_long(long, periods=sel_periods or None, countries=sel_countries or None,
                                  item_std=[s.split(" | ")[0] for s in sel_items] or None, label_contains=text or None, dims=dims)
        st.write(f"{len(sub):,} rows after filtering")
        shown = [c for c in ["year", "period", "lei", "country_bank", "item_std", "label"] + explore.DIM_COLS.get(ds, []) + ["amount"] if c in sub.columns]
        st.dataframe(sub[shown].head(2000), width="stretch", hide_index=True)
        g1, g2, g3 = st.columns(3)
        by = g1.multiselect("Group by", [c for c in ["year", "period", "country_bank", "lei", "item_std", "label"] + explore.DIM_COLS.get(ds, []) if c in sub.columns], default=["period"])
        fn = g2.selectbox("Aggregation", list(explore.FUNCS), index=0)
        piv = g3.checkbox("Pivot the last group column", value=False)
        if len(sub):
            agg = explore.aggregate_long(sub, by, fn)
            st.dataframe(agg, width="stretch", hide_index=True); download(agg, "aggregate.csv", "dl_exp")
            if piv and len(by) >= 2:
                pv = explore.pivot_long(sub, by[:-1], [by[-1]], fn); st.dataframe(pv, width="stretch")
            elif len(by) == 1 and len(agg) <= 400:
                st.bar_chart(agg.set_index(by[0]).iloc[:, -1])

# ------------------------------------------------------------------ charts
with tabs[3]:
    name = st.selectbox("Chart", list(charts.CHARTS))
    quarters = ["All"] + sorted(map(str, panel["quarter"].unique()))
    kw = {}
    if name in ("Capital distribution", "NPL ratio by country", "CET1 vs. NPL"):
        kw["quarter"] = st.selectbox("Quarter", quarters)
    if name == "Capital distribution":
        kw["ratio"] = st.selectbox("Ratio", list(charts.RATIOS))
    if name == "Bank trajectories":
        pick = st.multiselect("Banks", names["label"].tolist(), default=names["label"].tolist()[:3])
        ratio = st.selectbox("Ratio", list(charts.RATIOS)); leis = names[names["label"].isin(pick)]["lei"].tolist()
        fig = charts.bank_trajectories(panel, leis, ratio)
    else:
        fig = charts.CHARTS[name](panel, **kw)
    st.pyplot(fig)
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    st.download_button("Download PNG", buf.getvalue(), file_name=f"{name.lower().replace(' ', '_')}.png", mime="image/png")

# ------------------------------------------------------------------ events
with tabs[4]:
    st.caption("Event E1: a bank compliant at t breaches an alert level in t+1 ... t+h. Levels are fractions in the data; enter percentages here.")
    e1, e2, e3, e4 = st.columns(4)
    lv = {"cet1_ratio": e1.number_input("CET1 alert level (%)", value=7.0) / 100, "tier1_ratio": e2.number_input("Tier 1 alert level (%)", value=8.5) / 100,
          "total_capital_ratio": e3.number_input("Total capital alert level (%)", value=10.5) / 100}
    hz = int(e4.number_input("Horizon (quarters)", value=4, min_value=1, max_value=8))
    lab = e1_labels(panel, lv, hz); rep = event_report(panel, lab)
    st.json(rep)
    st.success("GO: enough banks with events for E1") if rep["go_e1"] else st.warning("STOP: too few banks with E1 events with these data (see the rule in section 3.6)")
    download(lab.assign(quarter=lab["quarter"].astype(str)), "labels_e1.csv", "dl_lab")

# ------------------------------------------------------------------ indicators
with tabs[5]:
    ind = indicators.indicators_df()
    fam = st.multiselect("Family", sorted(ind["family"].unique())); q = st.text_input("Search", "")
    if fam: ind = ind[ind["family"].isin(fam)]
    if q: ind = ind[ind.apply(lambda r: q.lower() in " ".join(map(str, r)).lower(), axis=1)]
    st.dataframe(ind, width="stretch", hide_index=True)
