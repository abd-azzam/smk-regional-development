"""Manufacturing share of GDRP and of employment over time: district medians, one panel."""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = pd.read_csv("data/DAPOER/dapoer_presentday.csv")
d = d[(d.level == "district") & (d.year >= 2000)]
s = pd.DataFrame({"year": d.year,
    "old": d.gdp_manufacturing_pre2010 / d.gdp_constant_pre2010,   # pre-2010 base, ends 2013
    "new": d.gdp_manufacturing_sna08 / d.gdp_constant_sna08,       # SNA 2008 base, from 2010
    "emp": d.emp_industry / d.emp_total})
for c in ("old", "new", "emp"):
    s.loc[s[c] > 1, c] = np.nan                                    # impossible shares
s.loc[s.year < 2007, "emp"] = np.nan                               # only ~30 districts report before 2007
med = s.groupby("year").median().reindex(range(2000, 2021)) * 100  # missing years stay NaN: gaps, no interpolation

BLUE, ORANGE, GREY, INK = "#1f4e79", "#b5541c", "#7a7a7a", "#222222"  # blue = output, orange = jobs, grey = old base
plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]
fig, ax = plt.subplots(figsize=(9, 5.2))
ax.plot(med.index, med.old, color=GREY, lw=1.6, ls=(0, (4, 3)))
ax.plot(med.index, med.new, color=BLUE, lw=2.4)
ax.plot(med.index, med.emp, color=ORANGE, lw=2.4)
for c, col in (("new", BLUE), ("emp", ORANGE)):
    ax.plot(med.index, med[c], ls="", marker="o", ms=4, color=col)  # dots show real observations (gap at 2016)

def tag(x, y, text, color, dy=0):
    ax.annotate(text, (x, y), xytext=(8, dy), textcoords="offset points", color=color, fontsize=10, va="center", fontweight="bold")
tag(2020, med.new[2020], "Share of GDRP", BLUE, -6)
tag(2020, med.emp[2020], "Share of employment", ORANGE, 6)
ax.annotate("older GDRP series\n(pre-2010 base)", (2004, med.old[2004]), xytext=(0, 16), textcoords="offset points",
            color=GREY, fontsize=9, ha="center")

ax.set_ylim(0, 10); ax.margins(x=0); ax.set_xlim(2000, 2020); ax.set_xticks(range(2000, 2021, 4))
ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
ax.grid(axis="y", color="#e3e3e3", lw=.8); ax.set_axisbelow(True)
for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
ax.tick_params(length=0, labelsize=10, colors=INK)
fig.subplots_adjust(top=.80, bottom=.17, right=.80)
fig.text(.075, .93, "Output share of manufacturing held flat; its job share rose after 2015",
         fontsize=13, fontweight="bold", color=INK, ha="left")
fig.text(.075, .87, "Median across Indonesian districts (kabupaten and kota), 2000-2020",
         fontsize=10, color=GREY, ha="left")
n = s.groupby("year").count()
fig.text(.075, .04, f"Source: DAPOER. {n.new[n.new>0].min()}-{n.new.max()} districts a year for GDRP, "
         f"{n.emp[n.emp>0].min()}-{n.emp.max()} for employment. Employment starts in 2007 (fewer than 35 districts report before) "
         "and has no 2016 data.\nEmployment is the DAPOER industry series, taken to be manufacturing. Its rise after 2015 is not yet checked against the source metadata.",
         fontsize=7.5, color=GREY, ha="left", va="bottom")
fig.savefig("Result/mfg_share_over_time.png", dpi=200)
