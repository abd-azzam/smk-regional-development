"""Scrape all upper-secondary schools from referensi.data.kemendikdasmen.go.id.

Covers SMA / MA / SMK / MAK / SLB in one consistent frame -- which is the point.
The SMK file already in data/ came from a different site; a ratio whose numerator
and denominator come from different sources produces artefacts you cannot later
diagnose, so both sides get re-scraped from here.

Two fields this source has that smk.kemendikdasmen.go.id lacks:
  Bentuk Pendidikan   -- SMA / MA / SMK / MAK / SLB
  Kementerian Pembina -- Kemendikdasmen vs Kementerian Agama (the madrasah split)

Phase 1: kabupaten -> kecamatan codes   (~526 requests, seeded from the crosswalk)
Phase 2: kecamatan -> school rows       (~7,200 requests)
Phase 3: npsn detail -> founding date   (~43,000 requests)
Phase 4: write data/DIKMEN/dikmen_schools.csv

Every phase checkpoints to JSONL and skips completed work, so a crash or Ctrl-C
resumes. Re-running after a partial run is cheap and safe.
"""
import csv
import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://referensi.data.kemendikdasmen.go.id"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "DIKMEN")
CACHE = os.path.join(HERE, ".dikmen_cache")
KEC_JSONL = os.path.join(CACHE, "kecamatan.jsonl")
ROSTER_JSONL = os.path.join(CACHE, "roster.jsonl")
DETAIL_JSONL = os.path.join(CACHE, "detail.jsonl")
CROSSWALK = os.path.join(HERE, "data", "crosswalk", "kabkota_crosswalk.csv")

# 6 workers, no artificial sleep -- network latency paces it to roughly 10 req/s.
# This project already scraped 14k schools off a sibling site at 8; 6 is a notch
# gentler on what is, after all, someone's public ministry server.
WORKERS = 6

_local = threading.local()
_lock = threading.Lock()


def sess():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _local.s = s
    return _local.s


def get(url, tries=4):
    for i in range(tries):
        try:
            r = sess().get(url, timeout=60)
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


def run(todo, fn, label, every):
    n = [0]

    def work(item):
        fn(item)
        n[0] += 1
        if n[0] % every == 0:
            print(f"  {label} {n[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))


def cells(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).strip()
            for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


# ---------- phase 1: kabupaten -> kecamatan ----------

def phase1(kab_codes):
    done = load_done(KEC_JSONL, "kab", ok_only=True)
    todo = [k for k in kab_codes if k not in done]
    print(f"phase1: {len(done)} kabupaten cached, {len(todo)} to fetch", flush=True)

    def work(kab):
        html = get(f"{BASE}/pendidikan/dikmen/{kab}/2")
        kecs = list(dict.fromkeys(re.findall(r'href="[^"]*dikmen/(\d{6})/3"', html or "")))
        append(KEC_JSONL, {"kab": kab, "kecamatan": kecs, "ok": html is not None})

    run(todo, work, "kab", 50)
    return load_done(KEC_JSONL, "kab")


# ---------- phase 2: kecamatan -> school roster ----------

def phase2(kec_codes):
    done = load_done(ROSTER_JSONL, "kec", ok_only=True)
    todo = [k for k in kec_codes if k not in done]
    print(f"phase2: {len(done)} kecamatan cached, {len(todo)} to fetch", flush=True)

    def work(kec):
        html = get(f"{BASE}/pendidikan/dikmen/{kec}/3")
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S):
            m = re.search(r'href="[^"]*npsn/(\d+)"', tr)
            c = cells(tr)
            if m and len(c) >= 6:
                rows.append({"npsn": m.group(1), "nama": c[2], "alamat": c[3],
                             "kelurahan": c[4], "status": c[5]})
        append(ROSTER_JSONL, {"kec": kec, "rows": rows, "ok": html is not None})

    run(todo, work, "kec", 250)
    return load_done(ROSTER_JSONL, "kec")


# ---------- phase 3: npsn detail ----------

FIELDS = {
    "tanggal_sk_pendirian": r"Tanggal SK\.? Pendirian\s*:\s*([\d\-]+)",
    "nomor_sk_pendirian": r"No\.? SK\.? Pendirian\s*:\s*(.*?)\s*(?:&nbsp|Tanggal)",
    "bentuk": r"Bentuk Pendidikan\s*:\s*([A-Za-z ]+?)\s*(?:&|Jenjang)",
    "kementerian": r"Kementerian Pembina\s*:\s*(.+?)\s*(?:&nbsp|Naungan)",
    "naungan": r"Naungan\s*:\s*(.+?)\s*(?:&nbsp|NPYP)",
}


def phase3(npsns):
    done = load_done(DETAIL_JSONL, "npsn", ok_only=True)
    todo = [n for n in npsns if n not in done]
    print(f"phase3: {len(done)} details cached, {len(todo)} to fetch", flush=True)

    def work(npsn):
        html = get(f"{BASE}/pendidikan/npsn/{npsn}")
        rec = {"npsn": npsn, "ok": html is not None, "gone": html == ""}
        if html:
            flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
            for k, pat in FIELDS.items():
                m = re.search(pat, flat)
                rec[k] = m.group(1).strip() if m else ""
        append(DETAIL_JSONL, rec)

    run(todo, work, "detail", 1000)
    return load_done(DETAIL_JSONL, "npsn")


# ---------- phase 4: write ----------

# Same epoch placeholders Dapodik uses elsewhere for "no date recorded" -- see the
# note in scrape_smk.py. Dates here are dd-mm-yyyy rather than "01 Jan 1900".
SENTINEL = {"01-01-1900", "01-01-1901"}


def year(s):
    if (s or "").strip() in SENTINEL:
        return ""
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", s or "")
    return m.group(1) if m else ""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)

    xw = {r["dapodik_kode"]: r for r in
          csv.DictReader(open(CROSSWALK, encoding="utf-8-sig"))}
    print(f"seeded {len(xw)} kabupaten from the crosswalk", flush=True)

    kp = phase1(list(xw))
    kec2kab = {k: kab for kab, r in kp.items() for k in r["kecamatan"]}
    print(f"phase1 done: {len(kec2kab)} kecamatan, "
          f"{sum(1 for r in kp.values() if not r['ok'])} failed", flush=True)

    rp = phase2(list(kec2kab))
    schools = {}
    for kec, r in rp.items():
        for row in r["rows"]:
            schools.setdefault(row["npsn"], {**row, "kec": kec})
    print(f"phase2 done: {len(schools)} unique NPSN, "
          f"{sum(1 for r in rp.values() if not r['ok'])} failed", flush=True)

    dd = phase3(list(schools))
    print(f"phase3 done: {len(dd)} details, "
          f"{sum(1 for r in dd.values() if not r['ok'])} failed, "
          f"{sum(1 for r in dd.values() if r.get('gone'))} dead links", flush=True)

    rows = []
    for npsn, s in schools.items():
        d = dd.get(npsn, {})
        kab = xw.get(kec2kab.get(s["kec"], ""), {})
        rows.append({
            "npsn": npsn, "nama": s["nama"], "bentuk": d.get("bentuk", ""),
            "status": s["status"], "kementerian": d.get("kementerian", ""),
            "naungan": d.get("naungan", ""),
            "provinsi": kab.get("provinsi", ""), "kab_kota": kab.get("kab_kota", ""),
            "bps_kode": kab.get("bps_kode", ""), "dapodik_kec": s["kec"],
            "kelurahan": s["kelurahan"], "alamat": s["alamat"],
            "tahun_berdiri": year(d.get("tanggal_sk_pendirian", "")),
            "tanggal_sk_pendirian": d.get("tanggal_sk_pendirian", ""),
            "nomor_sk_pendirian": d.get("nomor_sk_pendirian", ""),
        })
    rows.sort(key=lambda r: (r["provinsi"], r["kab_kota"], r["bentuk"], r["nama"]))

    out = os.path.join(OUT_DIR, "dikmen_schools.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} rows)", flush=True)

    print("  by bentuk:      ", dict(Counter(r["bentuk"] for r in rows).most_common()))
    print("  by kementerian: ", dict(Counter(r["kementerian"][:24] for r in rows).most_common()))
    miss = sum(1 for r in rows if not r["tahun_berdiri"])
    print(f"  missing tahun_berdiri: {miss} ({miss / len(rows) * 100:.1f}%)")
    nobps = sum(1 for r in rows if not r["bps_kode"])
    if nobps:
        print(f"  WARNING: {nobps} rows failed to reach a BPS code")


if __name__ == "__main__":
    main()
