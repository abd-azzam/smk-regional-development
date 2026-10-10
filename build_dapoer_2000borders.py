"""Aggregate dapoer_wide (514 present-day districts) onto constant year-2000
borders (341 units), so it can be merged with analysis_panel_full without the
territory mismatch.

WHY: DAPOER codes change meaning as districts split. BPS code 1201 "Nias" covers
~700,000 people in 2003 and ~132,000 in 2010 -- same code, a sixth of the area.
The analysis panel holds year-2000 borders, so merging the two raw makes the
numerator and denominator describe different territory. For Nias in 2010 that is
a 5.8x error in openings per capita.

RULES (the same three decisions build_analysis_panel.py already makes):
  1. Ancestry from Bazzi & Gudgeon's kabpanel19802014usingUndangUndang.dta.
  2. EXTENSIVE (money, counts) SUM into the parent.
     INTENSIVE (rates, shares, per-capita) are POPULATION-WEIGHTED means.
  3. COVERAGE GUARD -- new here. build_analysis_panel.py uses sum(min_count=1),
     which sums whatever children happen to report, so a parent-year with one
     silent child is quietly too low. Here a parent-year is kept only if the
     reporting children cover at least COVERAGE of the parent's population.
     Measured cost of the strict rule is 0-6% of parent-years; see the printout.

Writes data/DAPOER/dapoer_wide.{csv,dta} -- THE analysis file -- from the
raw present-day intermediate dapoer_presentday.csv.
Never writes to analysis_panel_full.

    python build_dapoer_2000borders.py
"""
import os
import re
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WIDE = os.path.join(HERE, "data", "DAPOER", "dapoer_presentday.csv")
LABELS_IN = os.path.join(HERE, "data", "DAPOER", "dapoer_presentday_labels.do")
KABPANEL = os.path.join(HERE, "data", "AEJApp_2019_0309_Replication", "data",
                        "cleaningfiles", "kabpanel19802014usingUndangUndang.dta")
PANEL = os.path.join(HERE, "data", "PANEL", "analysis_panel_full.csv")
OUT_CSV = os.path.join(HERE, "data", "DAPOER", "dapoer_wide.csv")
OUT_DTA = os.path.join(HERE, "data", "DAPOER", "dapoer_wide.dta")
OUT_DO = os.path.join(HERE, "data", "DAPOER", "dapoer_labels.do")

# Require the reporting children to cover this share of the parent's population.
# 1.0 = every child must report. Lower it here if you want to trade accuracy for
# rows; the printout tells you exactly what each level costs.
COVERAGE = 1.0

IDS = ["geo_code", "geo_name", "bps_kode", "level", "prov_code", "year"]

# Province-level only -- no district observations at all, nothing to aggregate.
SKIP = ["credit_manufacturing", "export_manufactured", "export_manufactured_misc",
        "import_manufactured", "import_manufactured_misc"]

# Already at year-2000 borders (they came from analysis_panel_full). Re-joined
# at the end rather than aggregated, or they would be double-counted.
FROM_PANEL = ["open_smk_total", "open_SMK_negeri", "open_SMK_swasta"]

# Rates, ratios and per-capita figures. These do NOT add up.
# hh_expenditure_* are per capita despite being in IDR: summing is meaningless.
INTENSIVE = [
    "poverty_rate", "literacy_15up", "morbidity_rate", "skilled_birth_attendance",
    "urban_share", "rural_share", "urban_share_susenas",
    "enrollment_primary", "enrollment_junior_secondary", "enrollment_senior_secondary",
    "access_electricity", "access_water", "access_sanitation", "access_phone",
    "hh_expenditure_pc", "hh_expenditure_pc_edu", "hh_expenditure_pc_health",
    "hh_expenditure_poorest20",
]


def ancestry():
    """present-day BPS code -> constant-2000 parent code, + name and child count."""
    kp = pd.read_stata(KABPANEL, convert_categoricals=False)
    anc, names, children = {}, {}, Counter()
    for _, r in kp.iterrows():
        try:
            now, then = str(int(float(r["id_jan14"]))), str(int(float(r["id_dec00"])))
        except (TypeError, ValueError):
            continue
        anc[now] = then
        children[then] += 1
        nm = str(r.get("kab_dec00") or "").strip()
        if nm and nm.lower() != "nan":
            names.setdefault(then, nm)
    return anc, names, children


def main():
    anc, unit_names, n_children = ancestry()
    d = pd.read_csv(WIDE, encoding="utf-8-sig")
    d = d[d.level == "district"].copy()

    d["unit"] = d.bps_kode.astype("Int64").astype(str).map(anc)
    unmapped = sorted(d.loc[d.unit.isna(), "geo_name"].unique())
    d = d[d.unit.notna()].copy()
    print("districts mapped to 2000 parents: %d (%d unmapped: %s)"
          % (d.bps_kode.nunique(), len(unmapped), ", ".join(unmapped) or "none"))

    ind = [c for c in d.columns if c not in IDS + ["unit"]]
    extensive = [c for c in ind if c not in INTENSIVE + SKIP + FROM_PANEL]
    unclassified = set(ind) - set(extensive) - set(INTENSIVE) - set(SKIP) - set(FROM_PANEL)
    assert not unclassified, "unclassified indicators: %s" % sorted(unclassified)
    print("indicators: %d extensive (sum), %d intensive (pop-weighted), "
          "%d province-only skipped, %d taken from the panel"
          % (len(extensive), len(INTENSIVE), len(SKIP), len(FROM_PANEL)))

    g = d.groupby(["unit", "year"])
    pop_all = g.population.sum(min_count=1).rename("pop_all")

    out = {}
    rejected = Counter()
    for c in extensive + INTENSIVE:
        # coverage = share of the parent's population held by children reporting c
        rep = d[d[c].notna()].groupby(["unit", "year"]).population.sum()
        cov = (rep / pop_all).reindex(pop_all.index)
        ok = cov >= COVERAGE - 1e-9

        if c in INTENSIVE:
            sub = d[d[c].notna() & d.population.notna() & (d.population > 0)]
            num = (sub[c] * sub.population).groupby([sub.unit, sub.year]).sum()
            den = sub.population.groupby([sub.unit, sub.year]).sum()
            val = (num / den).reindex(pop_all.index)
        else:
            val = g[c].sum(min_count=1)

        rejected[c] = int((val.notna() & ~ok).sum())
        out[c] = val.where(ok)

    P = pd.DataFrame(out).reset_index()
    P["unit_name"] = P.unit.map(unit_names)
    P["n_children"] = P.unit.map(n_children)
    P["unit"] = P.unit.astype(int)

    # openings come back from the panel, already on 2000 borders
    pan = pd.read_csv(PANEL, usecols=["unit", "year"] + FROM_PANEL)
    P = P.merge(pan, on=["unit", "year"], how="left")

    lead = ["unit", "unit_name", "n_children", "year"] + FROM_PANEL
    P = P[lead + [c for c in P.columns if c not in lead]]
    P = P.sort_values(["unit", "year"]).reset_index(drop=True)

    P.to_csv(OUT_CSV, index=False, encoding="utf-8")

    # --- labels: reuse dapoer_labels.do, add the panel-side ones ---
    lab = {}
    for line in open(LABELS_IN, encoding="utf-8"):
        m = re.match(r'label var (\S+)\s+"(.*)"\s*$', line.strip())
        if m and m.group(1) in P.columns:
            lab[m.group(1)] = m.group(2)[:80]
    lab.update({
        "unit": "Constant year-2000 BPS district code (merge key)",
        "unit_name": "Year-2000 district name",
        "n_children": "Present-day districts inside this year-2000 unit",
        "year": "Year",
        **{c: "New schools opened this year (from analysis_panel_full)" for c in FROM_PANEL},
    })
    with open(OUT_DO, "w", encoding="utf-8") as fh:
        fh.write("* labels for dapoer_wide.dta (constant year-2000 borders)\n")
        for c in P.columns:
            if c in lab:
                fh.write('label var %-30s "%s"\n' % (c, lab[c].replace('"', "'")))

    d_out = P.copy()
    d_out["unit_name"] = d_out.unit_name.fillna("").astype(str)
    d_out.to_stata(OUT_DTA, write_index=False, version=118, variable_labels=lab)

    # --- report ---
    print("aggregated: %d units x %d years = %d rows, %d columns"
          % (P.unit.nunique(), P.year.nunique(), len(P), P.shape[1]))
    worst = [(v, n) for v, n in rejected.most_common() if n]
    print("cells rejected by the %.0f%% coverage guard: %d total, %d variables affected"
          % (100 * COVERAGE, sum(rejected.values()), len(worst)))
    for v, n in worst[:10]:
        kept = int(P[v].notna().sum())
        print("    %-30s rejected %5d, kept %5d (%.1f%% kept)"
              % (v, n, kept, 100 * kept / max(1, kept + n)))
    print("wrote", OUT_CSV)
    print("wrote", OUT_DTA)
    print("wrote", OUT_DO)


if __name__ == "__main__":
    main()
