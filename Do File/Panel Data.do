import delimited "analysis_panel_full.csv", encoding(utf-8) clear
destring unit, replace

*Clean the known problems — still outstanding
gen bad_splice = inlist(unit, 1408,1412,1505,1507,3514,6407,6473,7305 /*+2*/)
gen flag_bad = (poverty_rate>100 & !mi(poverty_rate)) ///
             | (literacy_15up>100 & !mi(literacy_15up)) ///
             | (emp_share_agriculture>1 & !mi(emp_share_agriculture))
tab flag_bad

gen ln_gdppc = ln(gdp_per_capita)

*xtsum
xtset unit year
xtsum smk_share smk_per_100k upper_sec_total gdp_per_capita if inrange(year,2001,2020)

*Plot 
preserve
keep if inrange(year,2001,2020)
collapse (p10) p10=smk_share (p50) med=smk_share (p90) p90=smk_share, by(year)
twoway (line med year) (line p10 year, lpattern(dash)) (line p90 year, lpattern(dash)), ///
    ytitle("SMK share of upper-secondary") legend(order(1 "median" 2 "p10" 3 "p90"))
restore

** --- FE ladder ---
gen ln_gdppc = ln(gdp_per_capita)
gen ln_pop   = ln(population)
local c urban_share poverty_rate literacy_15up ln_pop

reg   ln_gdppc smk_share `c'          if inrange(year,2001,2020), cluster(unit)
est store m1
reg   ln_gdppc smk_share `c' i.year   if inrange(year,2001,2020), cluster(unit)
est store m2
xtreg ln_gdppc smk_share `c'          if inrange(year,2001,2020), fe cluster(unit)
est store m3
xtreg ln_gdppc smk_share `c' i.year   if inrange(year,2001,2020), fe cluster(unit)
est store m4
est table m1 m2 m3 m4, b(%9.4f) se stats(N r2)

** FE Ladder but with Employment 
xtreg emp_share_industry smk_share `c' i.year if inrange(year,2001,2020), fe cluster(unit)

xtreg ln_gdppc L3.smk_share `c' i.year if inrange(year,2001,2020), fe cluster(unit)
xtreg emp_share_industry L3.smk_share `c' i.year if inrange(year,2001,2020), fe cluster(unit)

*placebo lead,  Regress employment on future smk_share:
xtreg emp_share_industry F3.smk_share `c' i.year if inrange(year,2001,2020), fe cluster(unit)