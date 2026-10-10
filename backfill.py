"""Recover schools dropped by the site's unstable pagination.

The list endpoint sorts by name with no tiebreaker, so at page boundaries rows with
equal names can repeat or vanish. A flat 1..1440 scrape therefore both duplicates
~11 rows and silently loses ~11 others.

Re-scraping province-scoped (and then kab/kota-scoped for any province that still
falls short) reshuffles those boundaries, so unioning the passes by NPSN converges
on the full set. Each scope is checked against the count the site reports for it.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import scrape_smk as m

PROV_JSONL = os.path.join(m.CACHE, "scoped.jsonl")


def reported(**scope):
    html = m.get(m.LIST, scope)
    mm = re.search(r"dari\s*([\d.]+)\s*sekolah", re.sub(r"<[^>]+>", " ", html or ""))
    return int(mm.group(1).replace(".", "")) if mm else None


def scrape_scope(scope, total):
    """Fetch every page of one filtered scope; return rows."""
    pages = -(-total // 10)
    out = []

    def work(p):
        q = dict(scope)
        q["page"] = p
        html = m.get(m.LIST, q)
        return m.parse_list(html) if html else []

    with ThreadPoolExecutor(m.WORKERS) as ex:
        for rows in ex.map(work, range(1, pages + 1)):
            out.extend(rows)
    return out


def load_union():
    """All rows seen so far, keyed by NPSN, from flat + scoped passes."""
    u = {}
    for line in open(m.LIST_JSONL, encoding="utf-8"):
        for r in json.loads(line)["rows"]:
            u.setdefault(r["npsn"], r)
    if os.path.exists(PROV_JSONL):
        for line in open(PROV_JSONL, encoding="utf-8"):
            r = json.loads(line)
            u.setdefault(r["npsn"], r)
    return u


def main():
    provs = sorted({r["provinsi"] for r in load_union().values()})
    print(f"{len(provs)} provinces")

    tot = dict(zip(provs, ThreadPoolExecutor(8).map(lambda p: reported(provinsi=p), provs)))
    print(f"site reports {sum(v for v in tot.values() if v)} across provinces\n")

    seen_before = len(load_union())
    for p in provs:
        n = tot[p]
        if not n:
            print(f"  !! {p}: no count"); continue
        u = load_union()
        have = sum(1 for r in u.values() if r["provinsi"] == p)
        if have >= n:
            continue
        rows = scrape_scope({"provinsi": p}, n)
        with open(PROV_JSONL, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        u = load_union()
        now = sum(1 for r in u.values() if r["provinsi"] == p)
        print(f"  {p}: {have} -> {now} / {n} {'OK' if now == n else 'STILL SHORT'}")

    # any province still short: drill into its kab/kota (smaller sort scopes)
    u = load_union()
    for p in provs:
        n = tot[p]
        have = sum(1 for r in u.values() if r["provinsi"] == p)
        if not n or have >= n:
            continue
        kabs = sorted({r["kab_kota"] for r in u.values() if r["provinsi"] == p})
        print(f"  drilling {p} ({have}/{n}) across {len(kabs)} kab/kota")
        for k in kabs:
            kn = reported(provinsi=p, kab_kota=k)
            if not kn:
                continue
            kh = sum(1 for r in u.values() if r["provinsi"] == p and r["kab_kota"] == k)
            if kh >= kn:
                continue
            rows = scrape_scope({"provinsi": p, "kab_kota": k}, kn)
            with open(PROV_JSONL, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            u = load_union()
            kh2 = sum(1 for r in u.values() if r["provinsi"] == p and r["kab_kota"] == k)
            print(f"    {k}: {kh} -> {kh2} / {kn}")

    u = load_union()
    print(f"\nunique NPSN: {seen_before} -> {len(u)}")
    short = [(p, sum(1 for r in u.values() if r["provinsi"] == p), tot[p])
             for p in provs if tot[p] and sum(1 for r in u.values() if r["provinsi"] == p) != tot[p]]
    if short:
        print("UNRECONCILED:")
        for p, h, n in short:
            print(f"  {p}: have {h}, site says {n}")
    else:
        print("all provinces reconcile with site counts")


if __name__ == "__main__":
    main()
