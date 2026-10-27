from te_engine.indicators import indicators_df
d = indicators_df()
order = ["Identifier","Quality","Capital (level)","Capital","Balance sheet","Earnings (level)","Earnings","Asset quality (level)","Asset quality","Concentration","Trend","Distance to alert level","Liquidity","Label"]
ro = {
"Identifier": "Câmpuri care identifică banca și momentul. Nu intră în modele; servesc la legarea fișierelor, la filtrare și la agregare pe țări, ani sau ediții.",
"Quality": "Indicator de calitate a datelor: arată de ce unele valori lipsesc. Lipsa nu este aleatorie: o bancă fără FINREP nu raportează deloc active, capitaluri proprii, profit sau credite, deci toți indicatorii care depind de ele sunt goi pentru ea.",
"Capital (level)": "Sume în valoare absolută (în milioane EUR, presupus). Nu se folosesc direct ca variabile ale modelelor, ci pentru calculul ratelor și pentru verificarea coerenței datelor (de exemplu Tier 1 = CET1 + AT1).",
"Capital": "Rate de capital: cel mai important grup de indicatori. Intră în modele, în reperul bazat pe reguli (nivelurile de alertă 7%, 8,5% și 10,5%) și definesc evenimentul E1. Sunt stocate ca fracții (0,12 = 12%).",
"Balance sheet": "Mărimi contabile folosite ca control de dimensiune și ca numitori pentru alți indicatori.",
"Earnings (level)": "Profitul cumulat de la începutul anului fiscal și numărul de trimestre incluse; permit anualizarea profitului.",
"Earnings": "Profitabilitatea, componenta „E” din CAMELS. Împreună cu capitalul, este familia care ar trebui să apară pe primele două locuri în importanța SHAP (ipoteza H5).",
"Asset quality (level)": "Sume de credite brute, neperformante și de Stage 3; servesc la calculul ratelor de calitate a activelor și la verificări încrucișate între șabloane.",
"Asset quality": "Calitatea activelor, componenta „A” din CAMELS. Rata creditelor neperformante și ponderea Stage 2 sunt variabile ale modelelor, iar rata NPL este baza evenimentului E3.",
"Concentration": "Aproximări ale concentrării expunerilor. Expunerea pe client individual nu este publică în aceste date, deci concentrarea se măsoară prin indicele Herfindahl–Hirschman (suma pătratelor ponderilor), pe sectoare NACE și, când fișierul tr_sov este disponibil, pe țări emitente.",
"Trend": "Variații față de trimestrul anterior sau față de același trimestru al anului precedent; se calculează doar dacă acel trimestru există în date. Sunt variabilele testate în ipoteza H3 (valoarea indicatorilor de tendință).",
"Distance to alert level": "Distanța față de nivelurile de alertă ale evenimentului E1. Valoarea negativă înseamnă încălcare. Se folosește la reglarea marjei m a reperului R1 și pentru a vedea cât de aproape sunt băncile de un eveniment.",
"Liquidity": "Componenta „L” din CAMELS. Nu există în ediția 2020; se adaugă când ediții ulterioare o raportează.",
"Label": "Variabile construite pentru învățarea supervizată: eșantionul de predicție și ținta.",
}
L = ["# Dicționarul indicatorilor", "",
"Fiecare indicator al panelului bancă × trimestru, ce înseamnă, de unde se ia și la ce folosește în lucrare. Descrierile din tabele sunt în engleză, ca să poată fi preluate direct într-o anexă; explicațiile pe familii sunt în română. Aceeași listă este disponibilă în aplicație (fila Indicators) și în reports/indicators.csv.", "",
"Convenții: ratele sunt fracții (0,12 = 12%); sumele sunt probabil în milioane EUR (unitatea nu este declarată în fișierele primite); „derived” înseamnă calculat de aplicație din alte câmpuri.", ""]
for fam in order:
    sub = d[d.family == fam]
    if sub.empty: continue
    L += [f"## {fam}", "", ro[fam], ""]
    L += ["| Indicator | Definition and formula | Source | Use | Caution |", "|---|---|---|---|---|"]
    for _, r in sub.iterrows():
        defn = r.definition + (f" Formula: {r.formula}." if r.formula not in ("as reported", "derived", "") and r.formula.lower() != "as listed" else "")
        cells = [r.indicator, defn, r.source, r.use, r.caution or "-"]
        L.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    L.append("")
L += ["## Legătura cu ipotezele", "", "| Hypothesis | Indicators involved | Role |", "|---|---|---|",
"| H1a, H1b | all features of the capital, asset quality, earnings and concentration families | Inputs of logistic regression, Random Forest and XGBoost; capital ratios and alert levels also drive the rule benchmark |",
"| H2 | cet1_ratio, tier1_ratio, total_capital_ratio, min_headroom | First model alert vs. first breach of an alert level (lead time) |",
"| H3 | npl_delta_qoq, loan_growth_qoq, loan_growth_yoy, cet1_delta_qoq | Trend features compared with levels only |",
"| H4 | cet1_ratio, tier1_ratio, total_capital_ratio and the alert levels | Rule benchmark executed with a different configuration (BNM profile) |",
"| H5 | families Capital, Earnings, Asset quality, Concentration, Liquidity | Grouped SHAP importance per family |", ""]
open("INDICATORI.md","w").write("\n".join(L)); print("ok", len(L))
