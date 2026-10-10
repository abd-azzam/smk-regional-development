"""Build the canonical kab/kota crosswalk: Dapodik names/codes <-> BPS codes.

Everything (SMK, dikmen, BPS outcomes) merges through this table. Run:
    python build_crosswalk.py

Frame is the 514-unit, pre-2022 BPS set (34 provinces). That vintage is chosen
deliberately: constant boundaries are what the panel needs, so the 4 post-2022
Papua provinces are folded into their parents rather than tracked separately.

NOTE: pemekaran (2000-2014 district splits) is NOT handled here. This maps names
to codes at one fixed vintage. Mapping child kabupaten back to constant parents
needs an authoritative split list -- see README in data/crosswalk/.
"""
import csv, os, re, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (research; abdullah.azzam21@mhs.uinjkt.ac.id)"}
DIKMEN = "https://referensi.data.kemendikdasmen.go.id/pendidikan/dikmen"
BPS_SRC = ("https://raw.githubusercontent.com/edwardsamuel/"
           "Wilayah-Administratif-Indonesia/master/csv/regencies.csv")
OUT = "data/crosswalk/kabkota_crosswalk.csv"

# Dapodik name -> BPS code. Renames and spelling variants that no normalisation
# rule should be asked to guess. Each is a real administrative rename.
OVERRIDES = {
    "Kab. Pasangkayu": "7605",            # renamed from Mamuju Utara, 2017
    "Kab. Toba": "1206",                  # renamed from Toba Samosir, 2020
    "Kab. Kepulauan Tanimbar": "8101",    # renamed from Maluku Tenggara Barat, 2019
    "Kab. Kep. Siau Tagulandang Biaro": "7108",  # Dapodik adds a "Kep." BPS omits
    "Kab. Mahakam Ulu": "6411",           # BPS spells it Mahakam Hulu
}


def get(url, pause=0.3):
    time.sleep(pause)
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def cells(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).strip()
            for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def norm(s):
    """Normalise a kab/kota name to a comparable key."""
    s = s.upper()
    s = re.sub(r"^KAB\.?\s*ADM\.?\s+", "KABUPATEN ", s)
    s = re.sub(r"^KOTA\s*ADM\.?\s+", "KOTA ", s)
    s = re.sub(r"^KAB\.?\s+", "KABUPATEN ", s)
    s = s.replace("ADMINISTRASI ", "")          # BPS omits it, Dapodik uses it
    s = re.sub(r"\bKEP\.?\b", "KEPULAUAN", s)
    s = re.sub(r"[^A-Z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # The two sources disagree on word breaks constantly (Gunungkidul vs Gunung
    # Kidul, Tolitoli vs Toli-Toli), and BPS letter-spaces a few names outright
    # ("KOTA D U M A I"). Dropping every space inside the name settles all of it.
    # The kind prefix stays separate so Kabupaten X never collides with Kota X.
    kind, _, rest = s.partition(" ")
    rest = rest.replace(" ", "")
    rest = rest.replace("SIDEMPUAN", "SIDIMPUAN")   # Dapodik vs BPS vowel
    return f"{kind}|{rest}"


def fetch_dapodik():
    top = get(DIKMEN)
    codes = list(dict.fromkeys(re.findall(r'href="[^"]*dikmen/(\d{6})/1"', top)))
    names = [c[1] for c in map(cells, re.findall(r"<tr[^>]*>(.*?)</tr>", top, re.S))
             if len(c) >= 6 and c[2].isdigit()]
    prov = dict(zip(codes, names))

    rows = []
    for pk in codes:
        html = get(f"{DIKMEN}/{pk}/1")
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            m = re.search(r'href="[^"]*dikmen/(\d{6})/2"', tr)
            c = cells(tr)
            if m and len(c) >= 6 and c[2].isdigit():
                rows.append({"dapodik_prov": pk, "provinsi": prov[pk],
                             "dapodik_kode": m.group(1), "kab_kota": c[1],
                             "sma_sederajat": c[2], "smk_sederajat": c[3], "slb": c[4]})
    return rows


def fetch_bps():
    rows = []
    for line in get(BPS_SRC).splitlines():
        p = line.split(",", 2)
        if len(p) == 3:
            rows.append({"bps_kode": p[0], "bps_prov": p[1], "bps_nama": p[2].strip()})
    return rows


def build():
    dap, bps = fetch_dapodik(), fetch_bps()
    by_name = {norm(b["bps_nama"]): b for b in bps}
    by_code = {b["bps_kode"]: b for b in bps}

    out, unmatched = [], []
    for r in dap:
        if r["provinsi"] == "Luar Negeri":       # overseas schools, not a region
            continue
        b = by_code.get(OVERRIDES.get(r["kab_kota"], "")) or by_name.get(norm(r["kab_kota"]))
        if b:
            out.append({**r, "bps_kode": b["bps_kode"], "bps_prov": b["bps_prov"],
                        "bps_nama": b["bps_nama"]})
        else:
            unmatched.append(r["kab_kota"])

    # These must hold or every downstream merge is silently wrong.
    assert not unmatched, f"unmatched Dapodik units: {unmatched}"
    codes = [r["bps_kode"] for r in out]
    dupes = {c for c in codes if codes.count(c) > 1}
    assert not dupes, f"two Dapodik units mapped to one BPS code: {dupes}"
    assert len(out) == len(bps) == 514, f"expected 514<->514, got {len(out)}<->{len(bps)}"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"OK  {len(out)} units -> {OUT}  (bijective with BPS, no duplicate codes)")


if __name__ == "__main__":
    build()
