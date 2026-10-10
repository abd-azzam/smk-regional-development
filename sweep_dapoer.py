"""Density-check every INDO-DAPOER indicator and rank them by panel usability.

Written because picking indicators off the metadata listing failed twice. The
metadata says nothing about whether a series is actually populated: the 15-64 /
0-14 / 65+ age breakdowns are listed like any other but carry only census years
2005 and 2010, and SP.URB.TOTL.ZS looks interchangeable with
SP.URB.TOTL.ZS.SUS while holding a quarter of the observations.

Both failures share a cause -- judging a series by its name. This measures all 274
instead: how many districts carry data, over how many years, and whether the
series is district-level at all.

Output: data/DAPOER/indicator_density.csv, sorted by usability.

    python sweep_dapoer.py
"""
import csv
import json
import os
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (research; abdullah.azzam21@mhs.uinjkt.ac.id)"}
API = "https://api.worldbank.org/v2"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "DAPOER", "indicator_density.csv")


def get(url, tries=3, timeout=180):
    for i in range(tries):
        try:
            time.sleep(0.8)
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read())
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(4 * (i + 1))


def main():
    meta = get(f"{API}/indicator?source=45&format=json&per_page=1000")
    inds = meta[1] if meta and len(meta) > 1 else []
    print(f"sweeping {len(inds)} indicators", flush=True)

    rows = []
    for n, ind in enumerate(inds, 1):
        code, name = ind["id"], ind["name"]
        d = get(f"{API}/country/all/indicator/{code}?source=45&format=json&per_page=30000")
        recs = [r for r in (d[1] or []) if r.get("value") is not None] if d else []

        districts, provinces, years = set(), set(), set()
        for r in recs:
            g = r["country"]["value"]
            (provinces if "Prop." in g else districts).add(g)
            years.add(int(r["date"]))

        dens = round(len(recs) / len(districts), 1) if districts else 0.0
        rows.append({
            "code": code, "name": name[:110],
            "districts": len(districts), "provinces": len(provinces),
            "obs": len(recs),
            "year_min": min(years) if years else "", "year_max": max(years) if years else "",
            "yrs_per_district": dens,
            # A district panel needs breadth AND depth. Plenty of series have 500
            # districts and two census years; those are cross-sections, not panels.
            "verdict": ("PANEL" if len(districts) >= 400 and dens >= 10
                        else "THIN" if len(districts) >= 400
                        else "PROVINCE" if provinces and not districts
                        else "SPARSE"),
        })
        if n % 25 == 0:
            print(f"  {n}/{len(inds)}", flush=True)

    rank = {"PANEL": 0, "THIN": 1, "SPARSE": 2, "PROVINCE": 3}
    rows.sort(key=lambda r: (rank[r["verdict"]], -r["yrs_per_district"], -r["districts"]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"\nwrote {OUT}")
    print("  ", dict(Counter(r["verdict"] for r in rows)))
    print("\ntop 30 by usability:")
    for r in rows[:30]:
        print(f"  {r['code']:30s} {r['districts']:>4}d {r['yrs_per_district']:>5}y "
              f"{r['year_min']}-{r['year_max']}  {r['name'][:58]}")


if __name__ == "__main__":
    main()
