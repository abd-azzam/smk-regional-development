# kab/kota crosswalk

Canonical join table. Every merge between school data (Dapodik) and regional
outcome data (BPS) goes through `kabkota_crosswalk.csv`. Rebuild with
`python build_crosswalk.py` from the project root.

| File | Rows | Contents |
|---|---|---|
| `kabkota_crosswalk.csv` | 514 | Dapodik province/kab codes + names ↔ BPS kode + name, plus current SMA/SMK/SLB counts |
| `dapodik_kabkota.csv` | 526 | Raw Dapodik capture before matching (includes 12 `Luar Negeri` rows) |

## Sources and their standing

- **Dapodik side** — scraped from <https://referensi.data.kemendikdasmen.go.id/pendidikan/dikmen>,
  40 requests. Authoritative; it is the system the school data itself comes from.
- **BPS side** — `edwardsamuel/Wilayah-Administratif-Indonesia` on GitHub, a
  third-party mirror of the Permendagri kode wilayah master. **Not fetched from
  BPS directly.** It audits clean (514 rows, no malformed lines, all 34 pre-2022
  provinces, counts per province plausible) but it is a mirror, and it should be
  re-verified against a BPS or Permendagri publication before anything is
  published off it.

## Vintage: 514 units, pre-2022

The frame is the 34-province / 514-kabupaten set that predates the 2022 Papua
split. That is deliberate — the panel needs constant boundaries, so the four new
Papua provinces fold into their parents rather than appearing as new units.

## Verification (asserted in `build_crosswalk.py`, build fails if any breaks)

- 514 Dapodik units ↔ 514 BPS units, bijective
- no two Dapodik units share a BPS code
- no unmatched units

Merge-tested downstream: `smk_schools.csv` resolves 14,390/14,390 rows (100%),
512 distinct kab/kota. The 2 units absent from that file simply have no SMK.

## Matching notes

Most names differ only in word breaks (Gunungkidul vs Gunung Kidul, Tolitoli vs
Toli-Toli), and BPS letter-spaces a few outright (`KOTA D U M A I`,
`KABUPATEN S I A K`). `norm()` drops every space inside the name, which settles
all of it, keeping the Kabupaten/Kota prefix separate so the two never collide.

Five entries are hardcoded in `OVERRIDES` because they are real administrative
renames no rule should guess: Pasangkayu (ex Mamuju Utara, 2017), Toba (ex Toba
Samosir, 2020), Kepulauan Tanimbar (ex Maluku Tenggara Barat, 2019), Siau
Tagulandang Biaro (Dapodik adds a "Kep."), Mahakam Ulu (BPS: Mahakam Hulu).

Fuzzy matching was tried and **removed**. At cutoff 0.88 it silently mapped
Kab. Toba → Kabupaten Tuban and Kepulauan Tanimbar → Kepulauan Anambas — wrong
provinces, wrong islands. Both were caught only by the duplicate-code assert.
Matching here is exact-or-override by design; do not reintroduce fuzzy.

## NOT handled: pemekaran

This maps names to codes at **one fixed vintage**. It does not map child
kabupaten back to constant parents across time.

That matters as soon as the panel starts before ~2014. Indonesia went from
roughly 340 kab/kota in 2000 to 514, so a panel over 2000–2024 is tracking units
that split mid-sample. Untreated, a split shows up as a fake "new SMK" that is
really a reassignment of an existing one.

Needs an authoritative parent–child list with split years. Do not reconstruct it
from BPS codes — code order does not encode parentage. Get an existing
harmonised panel rather than rebuilding from regulations.
