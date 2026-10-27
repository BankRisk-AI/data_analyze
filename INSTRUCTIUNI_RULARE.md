# Instrucțiuni de rulare a aplicației

## 1. Ce este și unde este punctul de intrare

Aplicația citește fișierele EBA în forma originală (CSV așa cum se descarcă, sau varianta Excel `.xlsx` a aceluiași fișier), le leagă între ele, le curăță și construiește panelul bancă × trimestru. Are două puncte de intrare:

| Scop | Comandă | Ce obții |
|---|---|---|
| **Aplicația interactivă** (filtrare, agregare, grafice, evenimente) | `streamlit run app.py` | interfață în browser, la adresa afișată în terminal (de regulă http://localhost:8501) |
| **Rulare în lot** (rapoarte, panel, grafice salvate) | `python -m te_engine all --data data --out reports` | folderul `reports/` cu `panel.csv`, `quality_report.md`, `data_inventory.md`, `event_report.json`, `labels_e1.csv`, `indicators.csv` și `charts/*.png` |

Fișierul `app.py` din rădăcina proiectului este punctul de intrare al aplicației; pachetul `te_engine/` conține toată logica (citire, panel, indicatori, etichete, grafice).

## 2. Instalare (o singură dată)

1. Python 3.11 sau mai nou.
2. În folderul proiectului:
   ```
   python -m venv .venv
   .venv\Scripts\activate          # Windows   (Linux/macOS: source .venv/bin/activate)
   pip install -r requirements.txt
   ```
3. Verificare: `python -m pytest -q` trebuie să afișeze `7 passed`.

## 3. Unde pui datele

Câte un folder pentru fiecare ediție, cu fișierele originale în interior:

```
data/
  year_2019/   tr_oth*.csv   tr_cre*.csv   tr_mrk*.csv   tr_sov*.csv   SDD*.xlsx   TR_Metadata*.xlsx
  year_2020/   (aceleași fișiere; numele pot avea sufixe, de exemplu tr_oth_2.csv)
  year_2021/   ...
```

- Fișierele de date pot fi `.csv` sau `.xlsx`; dacă există ambele, se folosește CSV.
- `tr_sov` este opțional (fără el, indicatorul `sovereign_hhi` rămâne necalculat). Lipsa unuia dintre `tr_oth`, `tr_cre`, `tr_mrk`, `SDD`, `TR_Metadata` este raportată în aplicație (fila Overview).
- Nu redenumi coloane și nu converti codificarea: aplicația recunoaște singură codificarea cp1252 a fișierelor EBA și elimină rândul agregat „All other banks".
- Pentru o ediție nouă, creezi folderul `year_YYYY` și apeși **Reload files** în bara laterală (sau repornești aplicația).

## 4. Aplicația interactivă, pe file

1. **Overview**: fișierele găsite pe ediții, verificările de calitate (identități contabile, unități), valorile lipsă, jurnalul de decizii și observațiile extreme marcate.
2. **Panel**: tabelul bancă × trimestru cu filtre (trimestre, țări, bănci), alegerea coloanelor, export CSV și **agregare** (grupare după trimestru, an, țară sau ediție; funcții mediană, medie, minim, maxim, număr, sumă).
3. **Explorer (original files)**: lucrează direct pe fișierele originale în format lung. Alegi fișierul (`tr_oth`, `tr_cre`, `tr_mrk`, `tr_sov`), filtrezi după perioadă, țara băncii, text din etichetă, indicator (căutare după cod sau etichetă) și după orice coloană de dimensiune (de exemplu `Perf_Status`, `NACE_codes`), apoi grupezi, agregi și, opțional, faci un tabel pivot. Coloana `item_std` este codul indicatorului din ediția 2020, ca același indicator să poată fi agregat peste ani, chiar dacă codurile originale diferă între ediții (corespondența se ia din SDD).
4. **Charts**: 9 grafice (capital în timp, distribuția capitalului, distanța față de pragul de alertă, NPL pe țări, echilibrul panelului, valori lipsă, traiectorii ale băncilor, corelații, CET1 vs. NPL), cu descărcare PNG.
5. **Events**: evenimentul E1 cu pragurile și orizontul modificabile; afișează raportul și mesajul GO/STOP din §3.6.
6. **Indicators**: dicționarul indicatorilor, cu filtrare și căutare (descrierea completă este în `INDICATORI.md`).

## 5. Rularea în lot

```
python -m te_engine all --data data --out reports                 # tot
python -m te_engine panel events --data data --out reports        # doar panel și evenimente
python -m te_engine charts --data data --out reports --years 2019 2020
```
Comenzile disponibile: `all`, `inventory`, `panel`, `events`, `charts`. Opțiunea `--years` restrânge ediția.

## 6. Probleme frecvente

- *„No folder named year_YYYY found"*: calea din bara laterală nu indică folderul `data` sau folderul edițiilor nu respectă numele `year_YYYY`.
- *Încărcare lentă*: fișierul `tr_cre` are circa 400.000 de rânduri pe ediție; prima încărcare durează câteva secunde, apoi datele sunt păstrate în memorie. Versiunile `.xlsx` ale fișierelor mari se citesc mult mai lent decât CSV.
- *Avertisment „item … unresolved / label differs"* în jurnal: un indicator nu a putut fi găsit sau are altă etichetă într-o ediție; indicatorul respectiv rămâne gol pentru acea ediție, nu este completat automat. Verifică în SDD-ul ediției.
- *Etichete E1 goale*: cu mai puțin de cinci trimestre consecutive în panel, nicio observație nu are orizontul complet de patru trimestre.
- *Unități*: sumele sunt probabil în milioane EUR; fișierele primite nu declară unitatea, deci verifică în ghidul fiecărei ediții.

## 7. Structura proiectului

```
app.py                  punctul de intrare al aplicației (Streamlit)
te_engine/
  discover.py           găsește folderele data/year_*
  io.py                 citește fișierele originale (csv cp1252 / xlsx), LEI, lista băncilor
  items.py              corespondența codurilor de indicatori între ediții (SDD)
  workspace.py          încarcă edițiile, tabele lungi cu item_std, panelul
  explore.py            filtrare, agregare, pivot pe tabelele lungi
  panel.py              panelul bancă × trimestru și indicatorii derivați
  quality.py            verificări de calitate
  labels.py             evenimentul E1 și raportul GO/STOP
  charts.py             graficele (etichete în engleză)
  indicators.py         dicționarul indicatorilor
  cli.py, __main__.py   rularea în lot
tests/                  7 teste automate
data/                   datele tale (year_*)
reports/                rezultatele rulării în lot
```
