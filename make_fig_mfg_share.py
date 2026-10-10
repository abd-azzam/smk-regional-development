"""Manufacturing share of GDRP and of employment over time: district median and IQR."""
import pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = pd.read_csv("data/DAPOER/dapoer_presentday.csv")
d = d[(d.level == "district") & (d.year >= 2000)]
s = pd.DataFrame({"year": d.year,
    "old": d.gdp_manufacturing_pre2010 / d.gdp_constant_pre2010,   # pre-2010 base, ends 2013
    "new": d.gdp_manufacturing_sna08 / d.gdp_constant_sna08,       # SNA 2008 base, from 2010
    "emp": d.emp_industry / d.emp_total})
s = s.where((s <= 1) | (s.columns == "year")) * 1  # drop impossible shares > 100%
s.loc[s.year.isin(range(2000, 2007)), "emp"] = float("nan")        # only ~30 districts report before 2007
g = s.groupby("year")
yrs = range(2000, 2021)

def band(ax, col, color, label):
    q = g[col].quantile([.25, .5, .75]).unstack().reindex(yrs).dropna()
    ax.fill_between(q.index, q[.25] * 100, q[.75] * 100, color=color, alpha=.2, lw=0)
    ax.plot(q.index, q[.5] * 100, color=color, marker="o", ms=3.5, label=label)
    return g[col].count()

fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
band(a1, "old", "#8c8c8c", "GDRP, pre-2010 base (to 2013)")
n = band(a1, "new", "#1f4e79", "GDRP, SNA 2008 base (from 2010)")
a1.set_ylabel("Manufacturing share of GDRP (%)"); a1.legend(frameon=False, loc="upper left")
ne = band(a2, "emp", "#b5541c", "Employment")
a2.set_ylabel("Manufacturing share of employment (%)"); a2.set_xticks(list(yrs)[::2])
a2.axvline(2016, ls=":", lw=.8, color="grey"); a2.text(2016, a2.get_ylim()[1] * .97, "no 2016 data\n(line interpolated)", fontsize=8, color="grey", ha="center", va="top")
fig.suptitle(f"Manufacturing share across districts, 2000-2020 (line = median, band = interquartile range)\n"
             f"districts per year: GDRP {n[n>0].min()}-{n.max()}, employment {ne[ne>0].min()}-{ne.max()}", fontsize=10.5)
fig.tight_layout(); fig.savefig("Result/mfg_share_over_time.png", dpi=200)
