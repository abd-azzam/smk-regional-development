"""Merge school treatment and INDO-DAPOER outcomes into one constant-border panel.

Three things here are decisions, not mechanics, and each is defensible in a
different direction:

1. CONSTANT 2000 BORDERS. Districts split throughout the window, so raw codes are
   not comparable over time. Children are aggregated back onto their 2000 parent
   using Bazzi & Gudgeon's Undang-Undang ancestry. 341 units instead of 514 --
   fewer units, but units that mean the same thing in 2001 and 2020.

2. EXTENSIVE vs INTENSIVE aggregation. Counts and totals (GDP, population,
   employment, schools) SUM into the parent. Rates (poverty, urban share,
   enrolment) are POPULATION-WEIGHTED means -- a plain average would let a tiny
   child district pull the parent's rate as hard as a large one.

3. GDP SPLICE. Indonesia rebased in 2010, so the pre-rebase constant-price series
   (to 2013) and the SNA 2008 series (from 2010) sit at different levels. They
   overlap 2010-2013; the old series is rescaled onto the new one by a
   unit-specific ratio computed on that overlap. Units without a usable overlap
   keep whichever series they have, flagged in `gdp_splice`.

    python build_analysis_panel.py
"""
import csv
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_crosswalk import norm  # noqa: E402

DAPOER = os.path.join(HERE, "data", "DAPOER", "dapoer_long.csv")
D2BPS = os.path.join(HERE, "data", "crosswalk", "dapoer_to_bps.csv")
KABPANEL = os.path.join(HERE, "data", "AEJApp_2019_0309_Replication", "data",
                        "cleaningfiles", "kabpanel19802014usingUndangUndang.dta")
SCHOOLS = os.path.join(HERE, "data", "PANEL", "school_panel_2000borders.csv")
OUT = os.path.join(HERE, "data", "PANEL", "analysis_panel_full.csv")

# Totals and counts -- these add up when children are folded into a parent.
EXTENSIVE = ["gdp_constant_pre2010", "gdp_constant_sna08", "gdp_constant_exoilgas",
             "gdp_manufacturing_pre2010", "gdp_manufacturing_sna08",
             "emp_industry", "emp_total", "emp_agriculture", "labor_force",
             "unemployed", "population", "schools_senior_secondary",
             "revenue_total", "revenue_dau", "revenue_own_source", "revenue_dak",
             "revenue_sharing", "expenditure_total", "expenditure_capital",
             "expenditure_education"]
# Rates, ratios, and per-capita figures -- these do NOT add up, so they are
# population-weighted. Note hh_expenditure_* are per capita despite being in IDR:
# summing them would be meaningless.
INTENSIVE = ["poverty_rate", "urban_share", "enrollment_senior_secondary",
             "enrollment_primary", "enrollment_junior_secondary", "literacy_15up",
             "hh_expenditure_pc", "hh_expenditure_poorest20",
             "access_electricity", "access_water", "access_sanitation",
             "morbidity_rate", "skilled_birth_attendance"]
OVERLAP = range(2010, 2014)


def ancestry():
    """present-day BPS code -> constant-2000 parent code, plus the parent's name
    and how many present-day districts it contains (a split-intensity measure)."""
    kp = pd.read_stata(KABPANEL, convert_categoricals=False)
    out, names, children = {}, {}, Counter()
    for _, r in kp.iterrows():
        try:
            now, then = str(int(float(r["id_jan14"]))), str(int(float(r["id_dec00"])))
        except (TypeError, ValueError):
            continue
        out[now] = then
        children[then] += 1
        nm = str(r.get("kab_dec00") or "").strip()
        if nm and nm.lower() != "nan":
            names.setdefault(then, nm)
    return out, names, children


def split_vars():
    """postSplit by unit-year, from Bazzi & Gudgeon's panel -- already keyed on
    constant-2000 districts, so it merges straight onto `unit`."""
    d = pd.read_stata(os.path.join(os.path.dirname(KABPANEL), "DAPOER_OD.dta"),
                      convert_categoricals=False)
    d = d.rename(columns={"originaldistrict2000": "unit", "postSplit": "post_split"})
    d["unit"] = d.unit.astype(int).astype(str)
    d["year"] = d.year.astype(int)
    # first year the unit is flagged post-split, carried to every row of that unit
    first = (d[d.post_split == 1].groupby("unit").year.min().rename("split_year"))
    return d[["unit", "year", "post_split"]], first


def main():
    anc, unit_names, n_children = ancestry()
    d2b = {r["geo_name"]: r["bps_kode"] for r in csv.DictReader(open(D2BPS, encoding="utf-8-sig"))}
    prov = {r["bps_kode"][:2]: r["provinsi"]
            for r in csv.DictReader(open(os.path.join(HERE, "data", "crosswalk",
                                                      "kabkota_crosswalk.csv"),
                                         encoding="utf-8-sig"))}

    df = pd.read_csv(DAPOER, encoding="utf-8-sig")
    df = df[df.level == "district"].copy()
    df["unit"] = df.geo_name.map(lambda g: anc.get(d2b.get(g, ""), ""))
    dropped = df[df.unit == ""].geo_name.nunique()
    df = df[df.unit != ""]
    print(f"dapoer districts mapped to constant-2000 units: "
          f"{df.geo_name.nunique()} ({dropped} unmapped)")

    wide = df.pivot_table(index=["geo_name", "unit", "year"], columns="indicator",
                          values="value", aggfunc="first").reset_index()
    for c in EXTENSIVE + INTENSIVE:
        if c not in wide:
            wide[c] = pd.NA

    # Extensive: plain sum. Intensive: weighted by that district-year's population,
    # falling back to an unweighted mean only where population itself is missing.
    agg = {}
    for c in EXTENSIVE:
        agg[c] = wide.groupby(["unit", "year"])[c].sum(min_count=1)
    for c in INTENSIVE:
        def wmean(g):
            v, w = g[c], g["population"]
            m = v.notna() & w.notna() & (w > 0)
            if m.any():
                return (v[m] * w[m]).sum() / w[m].sum()
            return v.mean()
        agg[c] = wide.groupby(["unit", "year"]).apply(wmean, include_groups=False)

    P = pd.DataFrame(agg).reset_index()
    print(f"aggregated: {P.unit.nunique()} units x {P.year.nunique()} years = {len(P)} rows")

    # --- GDP splice ---
    for new, old, label in [("gdp_constant_sna08", "gdp_constant_pre2010", "gdp"),
                            ("gdp_manufacturing_sna08", "gdp_manufacturing_pre2010", "gdp_manufacturing")]:
        ov = P[P.year.isin(OVERLAP)]
        ratio = {}
        for u, g in ov.groupby("unit"):
            a, b = g[new].sum(min_count=1), g[old].sum(min_count=1)
            if pd.notna(a) and pd.notna(b) and b > 0:
                ratio[u] = a / b
        med = pd.Series(ratio).median()

        def splice(r):
            if pd.notna(r[new]):
                return r[new], "sna08"
            if pd.notna(r[old]):
                k = ratio.get(r["unit"], med)
                return r[old] * k, ("rescaled" if r["unit"] in ratio else "rescaled_median")
            return pd.NA, "missing"

        vals = P.apply(splice, axis=1, result_type="expand")
        P[label], P[f"{label}_splice"] = vals[0], vals[1]
        print(f"  {label}: spliced on {len(ratio)} units, median ratio {med:.3f}")

    # --- merge school treatment ---
    S = pd.read_csv(SCHOOLS, encoding="utf-8-sig")
    S["track"] = S.bentuk.where(S.bentuk.isin(["SMK", "SMA", "MA", "MAK"]), "OTHER")
    S["key"] = S.track + "_" + S.status.str.lower()
    stock = S.pivot_table(index=["unit", "year"], columns="key", values="stock",
                          aggfunc="sum").fillna(0)
    opened = S.pivot_table(index=["unit", "year"], columns="key", values="opened",
                           aggfunc="sum").fillna(0).add_prefix("open_")
    T = stock.join(opened).reset_index()
    T["unit"] = T.unit.astype(str)
    P["unit"] = P.unit.astype(str)

    M = P.merge(T, on=["unit", "year"], how="inner")
    print(f"merged with school panel: {M.shape}, {M.unit.nunique()} units, "
          f"{M.year.min()}-{M.year.max()}")

    smk = [c for c in M.columns if c.startswith("SMK_") and not c.startswith("open_")]
    M["smk_total"] = M[smk].sum(axis=1)
    M["smk_per_100k"] = M.smk_total / M.population * 1e5
    M["gdp_per_capita"] = M.gdp / M.population
    M["emp_share_industry"] = M.emp_industry / M.emp_total
    M["emp_share_agriculture"] = M.emp_agriculture / M.emp_total
    M["unemployment_rate"] = M.unemployed / M.labor_force
    # Output composition, NOT a substitute for emp_share_industry: the two
    # correlate 0.50 in levels but -0.01 in within-unit changes, so under unit
    # fixed effects they carry unrelated information.
    M["mfg_share_gdp"] = M.gdp_manufacturing / M.gdp
    # Reconstructed stock, for checking against DAPOER's schools_senior_secondary.
    # Runs ~23% low and the gap widens with lookback -- schools that closed before
    # the 2026 snapshot are invisible to the scrape.
    M["scraped_stock"] = M[[c for c in M.columns
                            if c.split("_")[0] in ("SMA", "SMK", "MA", "MAK")
                            and not c.startswith("open_")]].sum(axis=1)

    # --- SMA vs SMK scope ---
    # The paper compares vocational against general upper-secondary schooling, so
    # the selector is `bentuk`, not the supervising ministry. Madrasah are excluded
    # because MA/MAK does not map onto general/vocational: madrasah deliver
    # vocational education as a programme inside a general MA ("MA Plus
    # Keterampilan") rather than as separate MAK institutions, of which only 10
    # exist nationally. Counting MAK would therefore miss most of what MORA
    # actually provides. The 126 SMA/SMK run by Kemenperin, KKP, Kemensos and
    # others are kept -- they are vocational or general schools regardless of who
    # administers them, and they are 0.4% of the total either way.
    M["sma_total"] = M.SMA_negeri + M.SMA_swasta
    M["upper_sec_total"] = M.sma_total + M.smk_total
    M["smk_share"] = M.smk_total / M.upper_sec_total          # composition
    M["smk_public_share"] = M.SMK_negeri / M.smk_total        # public vs private SMK
    M["open_smk_total"] = M.open_SMK_negeri + M.open_SMK_swasta
    M["open_sma_total"] = M.open_SMA_negeri + M.open_SMA_swasta

    # --- identifiers and pemekaran, so this file stands alone in Stata ---
    M["unit_name"] = M.unit.map(unit_names)
    # Papua is the one region where the constant-2000 codes and present-day BPS
    # codes disagree: Bazzi & Gudgeon number the Papua districts 91/92/93, while
    # current BPS reads 91 as Papua Barat, 92 as Papua Barat Daya (created 2022)
    # and 94 as Papua. Looking these up in the present-day crosswalk mislabels all
    # 14 units -- 91xx came out as "Papua Barat Daya", 92xx and 93xx as blank.
    # At year-2000 borders the whole region was a single province (Irian Jaya);
    # these labels are the modern split, applied for readability.
    prov = {**prov, "91": "Papua Barat", "92": "Papua", "93": "Papua"}
    M["province"] = M.unit.str[:2].map(prov)
    M["n_children"] = M.unit.map(n_children)      # present-day districts per parent
    sp, first = split_vars()
    M = M.merge(sp, on=["unit", "year"], how="left")
    M = M.merge(first, on="unit", how="left")
    M["post_split"] = M.post_split.fillna(0).astype(int)
    M["ever_split"] = (M.n_children > 1).astype(int)

    lead = ["unit", "unit_name", "province", "year", "n_children", "ever_split",
            "post_split", "split_year"]
    M = M[lead + [c for c in M.columns if c not in lead]]

    M.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\nwrote {OUT}  ({len(M)} rows, {len(M.columns)} cols)")
    print(f"  named units: {M.unit_name.notna().sum() / len(M) * 100:.0f}%   "
          f"ever_split units: {M[M.ever_split == 1].unit.nunique()}/{M.unit.nunique()}")

    core = ["gdp", "population", "emp_share_industry", "poverty_rate",
            "urban_share", "smk_per_100k"]
    print("\ncoverage on core variables (non-null share, 2001-2020):")
    w = M[(M.year >= 2001) & (M.year <= 2020)]
    for c in core:
        print(f"   {c:24s} {w[c].notna().mean() * 100:5.1f}%")

    # Validation: DAPOER's own senior-secondary school count vs the scrape.
    v = M[(M.schools_senior_secondary.notna()) & (M.year.between(2001, 2018))].copy()
    v["scraped"] = v[[c for c in M.columns
                      if c.split("_")[0] in ("SMA", "SMK", "MA", "MAK")
                      and not c.startswith("open_")]].sum(axis=1)
    if len(v):
        print(f"\nvalidation vs DAPOER school counts (n={len(v)}):")
        print(f"   correlation: {v.scraped.corr(v.schools_senior_secondary):.3f}")
        print(f"   scraped/DAPOER ratio: median {(v.scraped / v.schools_senior_secondary).median():.2f}")


if __name__ == "__main__":
    main()
