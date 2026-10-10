"""Pull district-level INDO-DAPOER series from the World Bank API.

INDO-DAPOER is source 45. It is not published as a bulk file and the DataBank UI
export is manual, but the v2 API serves it: 548 geographies (34 provinces + 514
districts) with data back to the 1970s for some series.

Two things about this source that will bite otherwise:

  * `country.id` is blank on every row. Geographies are identifiable only by
    `country.value`, formatted "Badung, Kab." / "Denpasar, Kota" / "Bali, Prop.".
  * Indonesia rebased its national accounts in 2010, so GDP comes in two vintages
    that must be spliced: the pre-rebase series ends 2013, the SNA 2008 series
    starts 2010. They overlap 2010-2013, which is where you calibrate the splice.

Indicators here were picked by verified density, not by the metadata listing --
several metadata-listed series (the 15-64 / 0-14 / 65+ age breakdowns) turn out to
carry only census years 2005 and 2010 and are useless in a panel.

    python fetch_dapoer.py
"""
import json
import os
import time
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0 (research; abdullah.azzam21@mhs.uinjkt.ac.id)"}
API = "https://api.worldbank.org/v2/country/all/indicator/{}?source=45&format=json&per_page=25000"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "DAPOER")

INDICATORS = {
    # outcome: GDP, both vintages -- splice at the 2010-2013 overlap
    "NA.GDP.INC.OG.KR": "gdp_constant_pre2010",
    "NA.GDP.INC.OG.SNA08.KR": "gdp_constant_sna08",
    "NA.GDP.EXC.OG.KR": "gdp_constant_exoilgas",
    "NA.GDP.MNF.KR": "gdp_manufacturing_pre2010",
    "NA.GDP.MNF.SNA08.KR": "gdp_manufacturing_sna08",
    # mechanism: the vocational-education claim is about industrial employment
    "SL.EMP.IND": "emp_industry",
    "SL.EMP.TOTL": "emp_total",
    "SL.EMP.AGR.FRST.FSH": "emp_agriculture",
    "SL.TLF": "labor_force",
    "SL.UEM.TOTL": "unemployed",
    # denominators and controls
    "SP.POP.TOTL": "population",
    "SI.POV.NAPR.ZS": "poverty_rate",
    # Use the SUSENAS urbanisation series, not SP.URB.TOTL.ZS. They look
    # interchangeable in the metadata; they are not. The plain series carries 477
    # districts at 3.9 years each (2000-2011), the SUSENAS one 514 at 20.6
    # (1996-2020). Same for SP.RUR.TOTL.ZS, which is equally thin.
    "SP.URB.TOTL.ZS.SUS": "urban_share",
    # validation: an independent count of upper-secondary schools, plus enrolment
    # as a throughput measure the school counts cannot give
    "SE.SCHL.SRSEC": "schools_senior_secondary",
    "SE.SRSEC.NENR.ZS": "enrollment_senior_secondary",

    # --- second batch, added after sweep_dapoer.py measured all 274 ---
    # fiscal. Wider than the Bazzi & Gudgeon extract, which stops at 2014. DAU is
    # the transfer mechanically tied to district splits: a new district gets its
    # own allocation, which is the fiscal consequence of pemekaran.
    "REV.TOTL.CR": "revenue_total",
    "REV.DAU.CR": "revenue_dau",
    "REV.OSRV.CR": "revenue_own_source",
    "REV.DAK.CR": "revenue_dak",
    "REV.RV.SHR.CR": "revenue_sharing",
    "EC.XPD.TOTL.CR": "expenditure_total",
    "EC.XPD.CAP.CR": "expenditure_capital",   # where school construction sits
    "FC.XPD.EDU.CR": "expenditure_education",
    # education pipeline. Junior secondary is demand-side for SMK; primary has no
    # plausible channel from SMK expansion, so it doubles as a placebo.
    "SE.PRM.NENR.ZS": "enrollment_primary",
    "SE.JRSEC.NENR.ZS": "enrollment_junior_secondary",
    "SE.LITR.15UP.ZS": "literacy_15up",
    # household welfare: measures living standards rather than production
    "HOU.XPD.PC.CR": "hh_expenditure_pc",
    "HOU.XPD.TOTL.20POOR.CR": "hh_expenditure_poorest20",
    # infrastructure access and health -- controls, and further placebo candidates
    "HOU.ELC.ACSN.ZS": "access_electricity",
    "HOU.H2O.ACSN.ZS": "access_water",
    "HOU.STA.ACSN.ZS": "access_sanitation",
    "SH.MORB.ZS": "morbidity_rate",
    "SH.STA.BRTC.ZS": "skilled_birth_attendance",
}


def fetch(code, tries=4):
    for i in range(tries):
        try:
            time.sleep(1)
            req = urllib.request.Request(API.format(code), headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=180).read())[1] or []
        except Exception as e:
            if i == tries - 1:
                print(f"  {code}: FAILED after {tries} tries ({type(e).__name__})")
                return []
            time.sleep(4 * (i + 1))


def main():
    os.makedirs(OUT, exist_ok=True)
    long_rows = []

    for code, alias in INDICATORS.items():
        rows = [r for r in fetch(code) if r.get("value") is not None]
        for r in rows:
            name = r["country"]["value"]
            long_rows.append({
                "geo_name": name,
                # "Prop." marks a province row; everything else is a district
                "level": "province" if "Prop." in name else "district",
                "year": int(r["date"]),
                "indicator": alias,
                "value": r["value"],
            })
        d = {r["country"]["value"] for r in rows if "Prop." not in r["country"]["value"]}
        yrs = sorted({int(r["date"]) for r in rows})
        span = f"{yrs[0]}-{yrs[-1]}" if yrs else "-"
        print(f"  {alias:30s} {len(d):>4} districts  {len(rows):>6} obs  {span}")

    import csv
    path = os.path.join(OUT, "dapoer_long.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["geo_name", "level", "year", "indicator", "value"])
        w.writeheader()
        w.writerows(long_rows)

    dist = [r for r in long_rows if r["level"] == "district"]
    print(f"\nwrote {path}")
    print(f"  {len(long_rows)} rows total, {len(dist)} district-level")
    print(f"  distinct districts: {len({r['geo_name'] for r in dist})}")
    yrs = [r["year"] for r in dist]
    print(f"  year range: {min(yrs)}-{max(yrs)}")
    print("  by indicator:", dict(Counter(r["indicator"] for r in dist).most_common(4)), "...")


if __name__ == "__main__":
    main()
