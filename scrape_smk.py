"""Scrape SMK data from smk.kemendikdasmen.go.id -> data/*.csv

Phase 1: list pages (10 rows/page, page size is server-locked) -> school rows + detail GUID
Phase 2: detail pages -> Tanggal SK Pendirian (the founding date)
Phase 3: aggregate to province / kab-kota CSVs

Both phases checkpoint to JSONL and skip completed work, so a crash or Ctrl-C resumes.
"""
import csv
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import lxml.html as LH
import requests

BASE = "https://smk.kemendikdasmen.go.id"
LIST = BASE + "/data-sekolah/list"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, ".smk_cache")
LIST_JSONL = os.path.join(CACHE, "list.jsonl")
DETAIL_JSONL = os.path.join(CACHE, "detail.jsonl")

WORKERS = 8
COLS = ["no", "npsn", "nama_smk", "status", "alamat", "provinsi", "kab_kota", "kecamatan", "telp", "email"]

_local = threading.local()
_lock = threading.Lock()


def sess():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _local.s = s
    return _local.s


def get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = sess().get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return ""  # site-side dead link: definitive, retrying never helps
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** i)
                continue
            return None
        except requests.RequestException:
            time.sleep(2 ** i)
    return None


def load_done(path, key, ok_only=False):
    """Return {key: record} already scraped.

    Records are append-only, so a later retry of the same key overwrites the earlier
    failure. ok_only drops failed records so callers re-fetch them.
    """
    done = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # truncated last line from a hard kill
                done[r[key]] = r
    if ok_only:
        done = {k: v for k, v in done.items() if v.get("ok")}
    return done


def append(path, rec):
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- phase 1: list ----------

def total_schools():
    html = get(LIST, {"page": 1})
    m = re.search(r"dari\s*([\d.]+)\s*sekolah", re.sub(r"<[^>]+>", " ", html or ""))
    return int(m.group(1).replace(".", "")) if m else None


def tbody(html):
    """Isolate the results <tbody> before parsing.

    The full page is ~1MB, nearly all of it the filter dropdowns; parsing it whole
    costs ~1.1s of GIL-held CPU per page, which serialises every worker thread.
    Slicing first drops that to ~0.005s.
    """
    i = html.find("<tbody")
    j = html.find("</tbody>", i)
    if i < 0 or j < 0:
        return None
    return LH.fromstring("<table>" + html[i:j + 8] + "</table>")


def parse_list(html):
    root = tbody(html)
    if root is None:
        return []
    out = []
    for tr in root.xpath("//tr"):
        tds = tr.xpath("./td")
        if len(tds) < len(COLS):
            continue
        rec = {c: tds[i].text_content().strip() for i, c in enumerate(COLS)}
        a = tr.xpath('.//a[contains(@href,"detail-sekolah")]/@href')
        rec["guid"] = a[0].rsplit("/", 1)[-1] if a else ""
        out.append(rec)
    return out


def phase1(pages):
    done = load_done(LIST_JSONL, "page", ok_only=True)
    todo = [p for p in range(1, pages + 1) if p not in done]
    print(f"phase1: {len(done)} pages cached, {len(todo)} to fetch", flush=True)
    n = [0]

    def work(p):
        html = get(LIST, {"page": p})
        rows = parse_list(html) if html else []
        append(LIST_JSONL, {"page": p, "rows": rows, "ok": html is not None})
        n[0] += 1
        if n[0] % 100 == 0:
            print(f"  list {n[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))
    return load_done(LIST_JSONL, "page")


# ---------- phase 2: detail ----------

PAIR = re.compile(r"<td[^>]*>\s*([^<>]{1,60}?)\s*</td>\s*<td[^>]*>\s*([^<>]*?)\s*</td>")


def parse_detail(html):
    """Detail pages are flat <td>Label</td><td>Value</td> rows; regex beats a tree build."""
    d = {}
    for k, v in PAIR.findall(html):
        d.setdefault(k.strip(), v.strip())
    return d


def phase2(guids):
    done = load_done(DETAIL_JSONL, "guid", ok_only=True)
    todo = [g for g in guids if g not in done]
    print(f"phase2: {len(done)} details cached, {len(todo)} to fetch", flush=True)
    n = [0]

    def work(g):
        html = get(f"{BASE}/detail-sekolah/{g}")
        d = parse_detail(html) if html else {}
        append(DETAIL_JSONL, {
            "guid": g,
            "tanggal_sk_pendirian": d.get("Tanggal SK Pendirian", ""),
            "nomor_sk_pendirian": d.get("Nomor SK Pendirian", ""),
            "tanggal_sk_operasional": d.get("Tanggal SK Operasional", "") or d.get("Tanggal Izin Operasional", ""),
            "ok": html is not None,
            "gone": html == "",
        })
        n[0] += 1
        if n[0] % 250 == 0:
            print(f"  detail {n[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))
    return load_done(DETAIL_JSONL, "guid")


# ---------- phase 3: write ----------

# Epoch placeholders Dapodik uses for "no date recorded", not real founding dates:
# 274 rows are exactly "01 Jan 1900" and 61 exactly "01 Jan 1901", with zero variation
# in month/day and including schools plainly not founded then. Genuinely old schools
# carry varied real dates (e.g. SMKN 1 Jakarta, "20 Mei 1906"), so only these two
# exact strings are treated as null. The raw date is still kept in the CSV.
SENTINEL_DATES = {"01 Jan 1900", "01 Jan 1901"}


def year(s):
    if (s or "").strip() in SENTINEL_DATES:
        return ""
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", s or "")
    return m.group(1) if m else ""


def wcsv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)", flush=True)


def counts(records, keyfn):
    tot, neg, swa = Counter(), Counter(), Counter()
    for r in records:
        k = keyfn(r)
        tot[k] += 1
        if r["status"].lower().startswith("negeri"):
            neg[k] += 1
        elif r["status"].lower().startswith("swasta"):
            swa[k] += 1
    return tot, neg, swa


def main():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    total = total_schools()
    if not total:
        sys.exit("could not read total school count")
    pages = -(-total // 10)
    print(f"site reports {total} schools -> {pages} list pages", flush=True)

    lp = phase1(pages)
    bad = [p for p, r in lp.items() if not r["ok"]]
    schools = [r for p in sorted(lp) for r in lp[p]["rows"]]

    # The site sorts by name with no tiebreaker, so page boundaries both repeat and
    # skip rows. backfill.py re-scrapes province-scoped to recover the skipped ones;
    # union both passes on NPSN (the national school id) to get the true set.
    scoped = os.path.join(CACHE, "scoped.jsonl")
    if os.path.exists(scoped):
        with open(scoped, encoding="utf-8") as f:
            schools += [json.loads(line) for line in f if line.strip()]

    seen, uniq = set(), []
    for s in schools:
        if s["npsn"] and s["npsn"] not in seen:
            seen.add(s["npsn"])
            uniq.append(s)
    print(f"phase1 done: {len(schools)} rows, {len(uniq)} unique NPSN, {len(bad)} failed pages", flush=True)

    dd = phase2([s["guid"] for s in uniq if s["guid"]])
    dbad = [g for g, r in dd.items() if not r["ok"]]
    gone = [g for g, r in dd.items() if r.get("gone")]
    print(f"phase2 done: {len(dd)} details, {len(dbad)} failed, {len(gone)} dead links (404 on site)", flush=True)

    for s in uniq:
        d = dd.get(s["guid"], {})
        s["tanggal_sk_pendirian"] = d.get("tanggal_sk_pendirian", "")
        s["nomor_sk_pendirian"] = d.get("nomor_sk_pendirian", "")
        s["tahun_berdiri"] = year(s["tanggal_sk_pendirian"])

    uniq.sort(key=lambda r: (r["provinsi"], r["kab_kota"], r["nama_smk"]))

    wcsv(os.path.join(DATA, "smk_schools.csv"),
         ["npsn", "nama_smk", "status", "provinsi", "kab_kota", "kecamatan", "alamat",
          "tahun_berdiri", "tanggal_sk_pendirian", "nomor_sk_pendirian", "telp", "email", "url_detail"],
         [[s["npsn"], s["nama_smk"], s["status"], s["provinsi"], s["kab_kota"], s["kecamatan"], s["alamat"],
           s["tahun_berdiri"], s["tanggal_sk_pendirian"], s["nomor_sk_pendirian"], s["telp"], s["email"],
           f"{BASE}/detail-sekolah/{s['guid']}"] for s in uniq])

    t, n, w = counts(uniq, lambda r: r["provinsi"])
    wcsv(os.path.join(DATA, "smk_by_province.csv"),
         ["provinsi", "total_smk", "negeri", "swasta"],
         [[p, t[p], n[p], w[p]] for p in sorted(t)])

    t2, n2, w2 = counts(uniq, lambda r: (r["provinsi"], r["kab_kota"]))
    wcsv(os.path.join(DATA, "smk_by_kabkota.csv"),
         ["provinsi", "kab_kota", "total_smk", "negeri", "swasta"],
         [[p, k, t2[(p, k)], n2[(p, k)], w2[(p, k)]] for p, k in sorted(t2)])

    print(f"\nTOTAL {len(uniq)} | Negeri {sum(n.values())} | Swasta {sum(w.values())}", flush=True)
    missing = sum(1 for s in uniq if not s["tahun_berdiri"])
    print(f"missing tahun_berdiri: {missing}", flush=True)
    if bad or dbad:
        print(f"WARNING: {len(bad)} list pages + {len(dbad)} detail pages failed. Re-run to retry.", flush=True)


if __name__ == "__main__":
    main()
