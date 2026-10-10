"""Aggregate scraped schools into a constant-border kabupaten x year panel.

Pemekaran makes raw kab/kota codes useless across time: Indonesia went from ~300
units in 1999 to 514, so a unit in 2024 is often a fragment of a different unit in
2000. Counting schools by present-day code would read a district split as school
growth.

Bazzi & Gudgeon's replication package solves this. Their
kabpanel19802014usingUndangUndang traces every 2014 unit's identity back through
~78 dated snapshots (Dec 1980 - Jan 2014), built from the Undang-Undang. Taking
the id column at a chosen date gives each present-day unit its ancestor, so
schools can be aggregated onto boundaries that never move.

Output: one row per (constant-border unit, year, bentuk, status) with the count of
schools founded that year, plus the running stock.

    python build_panel.py            # default: constant 2000 borders
    python build_panel.py --base 2010
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPL = os.path.join(HERE, "data", "AEJApp_2019_0309_Replication", "data", "cleaningfiles")
KABPANEL = os.path.join(REPL, "kabpanel19802014usingUndangUndang.dta")
SCHOOLS = os.path.join(HERE, "data", "DIKMEN", "dikmen_schools.csv")
OUT_DIR = os.path.join(HERE, "data", "PANEL")

# Which snapshot column defines the constant frame. dec00 gives 2000 borders
# (~312 units), dec10 gives 2010 borders (~438). Wider frame = fewer units but
# cleaner comparability the further back the window runs.
BASE_COL = {2000: "id_dec00", 2010: "id_dec10"}


def code(v):
    """Stata stores these as floats; the join needs the bare integer string."""
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return ""


def load_ancestry(base):
    col = BASE_COL[base]
    kp = pd.read_stata(KABPANEL, convert_categoricals=False)
    anc = {}
    for _, r in kp.iterrows():
        now, then = code(r.get("id_jan14")), code(r.get(col))
        if now and then:
            anc[now] = then
    print(f"ancestry: {len(anc)} present-day units -> "
          f"{len(set(anc.values()))} constant-{base} units")
    return anc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=int, default=2000, choices=[2000, 2010])
    args = ap.parse_args()

    if not os.path.exists(SCHOOLS):
        sys.exit(f"missing {SCHOOLS} -- run scrape_dikmen.py first")

    anc = load_ancestry(args.base)
    schools = list(csv.DictReader(open(SCHOOLS, encoding="utf-8-sig")))

    events = defaultdict(int)
    unmapped, undated = 0, 0
    for s in schools:
        unit = anc.get(s["bps_kode"])
        if not unit:
            unmapped += 1
            continue
        y = s["tahun_berdiri"]
        if not y.isdigit():
            undated += 1
            continue
        events[(unit, int(y), s["bentuk"], s["status"])] += 1

    print(f"schools: {len(schools)}  mapped+dated: {sum(events.values())}  "
          f"unmapped: {unmapped}  undated: {undated}")

    # Stock is the running sum of openings. It is a lower bound on the true
    # historical stock: the source lists schools alive today, so anything that
    # closed is invisible, and the gap widens the further back you look.
    years = range(1980, 2026)
    units = sorted({k[0] for k in events})
    kinds = sorted({(k[2], k[3]) for k in events})

    rows, stock = [], defaultdict(int)
    for u in units:
        for kind in kinds:
            stock[(u, kind)] = 0
        for y in years:
            for bentuk, status in kinds:
                n = events.get((u, y, bentuk, status), 0)
                stock[(u, (bentuk, status))] += n
                if n or stock[(u, (bentuk, status))]:
                    rows.append({"unit": u, "base_borders": args.base, "year": y,
                                 "bentuk": bentuk, "status": status,
                                 "opened": n, "stock": stock[(u, (bentuk, status))]})

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"school_panel_{args.base}borders.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"\nwrote {out}")
    print(f"  {len(units)} units x {len(kinds)} school types, {len(rows)} rows")
    smk = sum(r["opened"] for r in rows if r["bentuk"] == "SMK")
    print(f"  SMK openings covered: {smk}")


if __name__ == "__main__":
    main()
