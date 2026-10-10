*Import the data 
import delimited "analysis_panel_full.csv", encoding(utf-8) clear
destring unit, replace
describe, short

* does the panel have the shape it should?
codebook unit year, compact
tab year if !missing(gdp)

* where are the holes?
misstable summarize smk_total gdp population urban_share ///
    poverty_rate literacy_15up emp_share_industry

* is missingness random, or clustered in particular provinces?
tab province if missing(emp_share_industry) & inrange(year,2001,2020)

*magnitude check 
gen gdppc = gdp/population
sum gdppc if year==2010, detail

*contaminated splice units 
preserve
keep if inrange(year,2010,2013)
collapse (sum) gdp_constant_sna08 gdp_constant_pre2010, by(unit unit_name)
gen ratio = gdp_constant_sna08/gdp_constant_pre2010
sum ratio, detail
list unit unit_name ratio if ratio<1.5 | ratio>8, clean
restore

*Cross Section
preserve
keep if year==2010

gen ln_gdppc = ln(gdppc)
gen ln_pop   = ln(population)

sum ln_gdppc smk_per_100k urban_share poverty_rate literacy_15up ln_pop

*Run it
* bivariate first, so you can see what the controls do
reg ln_gdppc smk_per_100k, robust
estimates store m1

* with controls
reg ln_gdppc smk_per_100k urban_share poverty_rate literacy_15up ln_pop, robust
estimates store m2
estimates table m1 m2, b(%9.4f) se stats(N r2)

*post estimation
predict resid, residuals
egen z = std(resid)
list unit unit_name ln_gdppc smk_per_100k z if abs(z)>2.5, clean

rvfplot, yline(0)
vif

*scatter plot
preserve
keep if year==2010
gen gdppc = gdp/population
gen ln_gdppc = ln(gdppc)
twoway (scatter ln_gdppc smk_per_100k, mcolor(navy%60)) ///
       (lfit ln_gdppc smk_per_100k, lcolor(navy) lwidth(medium)), ///
    legend(on) ytitle("ln(GDP per capita)") xtitle("SMK per 100k population") ///
    title("2010 cross-section")
restore

*scatter plot with control 
preserve
keep if year==2010
gen gdppc = gdp/population
gen ln_gdppc = ln(gdppc)
gen ln_pop = ln(population)

reg ln_gdppc smk_per_100k urban_share poverty_rate literacy_15up ln_pop, robust
avplot smk_per_100k
restore