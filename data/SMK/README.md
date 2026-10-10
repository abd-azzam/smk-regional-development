# SMK data — smk.kemendikdasmen.go.id

Scraped 2026-07-16 from <https://smk.kemendikdasmen.go.id/data-sekolah>.
Reproduce with `python scrape_smk.py` then `python backfill.py` (both resumable).

## Files

| File | Rows | Contents |
|---|---|---|
| `smk_schools.csv` | 14,391 | One row per school: NPSN, name, status, province, kab/kota, kecamatan, address, founding year + raw decree date, phone, email, detail URL |
| `smk_by_province.csv` | 39 | Per province: `total_smk`, `negeri`, `swasta` |
| `smk_by_kabkota.csv` | 513 | Per kabupaten/kota: `total_smk`, `negeri`, `swasta` |

Totals reconcile exactly with the site: **14,391 total = 3,793 negeri + 10,598 swasta**,
and all 39 province counts match the site's own published figures. Kab/kota totals roll
up to province totals exactly. UTF-8 with BOM, so Excel opens them cleanly.

## Read this before using `tahun_berdiri`

**It is the SK Pendirian (establishment decree) year, not a verified build year.** The site
publishes no "year founded" field; `Tanggal SK Pendirian` is the closest thing. For older
schools the decree is often re-issued after administrative reorganisation, so it can
post-date actual operation. The raw date and decree number are kept in
`tanggal_sk_pendirian` / `nomor_sk_pendirian` so any row can be audited.

Known gaps, all originating in the source data rather than the scrape:

- **547 rows (3.8%) have no usable year.** Of these, 335 carried the epoch placeholders
  `01 Jan 1900` (274) or `01 Jan 1901` (61) — null sentinels, not real dates. Every one is
  Jan 1 with no variation, and they include schools such as SMKN 5 Bandung that plainly
  were not founded then. These are blanked in `tahun_berdiri`; the raw string is retained.
  Genuinely old schools keep their real dates (SMKN 1 Jakarta, `20 Mei 1906`).
- **19 schools have no detail page at all** — the site 404s on its own links, so no decree
  date exists to fetch. They are still counted in all totals.
- **2 rows are dated in the future** (`10 Agt 2033`, `13 Apr 2027`) — typos in the source.
  Left as-is rather than silently corrected.

Usable years: 13,844 / 14,391 (96.2%), spanning 1906–2033.

## One scraping caveat worth knowing

The site paginates with `ORDER BY nama` and no tiebreaker, so rows with identical names
drift across page boundaries: a flat page-1..1440 scrape both repeats ~11 rows and
silently **loses** ~11 others, while still returning a plausible-looking 14,391 total.
`backfill.py` re-scrapes province-scoped (which reshuffles those boundaries) and unions on
NPSN until every province matches the site's reported count. Anyone re-scraping this site
by flat pagination alone will be quietly short.
