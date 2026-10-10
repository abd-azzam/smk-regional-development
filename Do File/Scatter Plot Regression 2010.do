* after the corrected regressions, still inside preserve/restore
reg ln_gdppc smk_per_100k if year==2010, robust
outreg2 using regression.doc, replace ctitle(Model 1)
reg ln_gdppc smk_per_100k urban_share poverty_rate literacy_15up ln_pop if year==2010, robust
outreg2 using regression.doc, append ctitle(Model 2)

reg emp_industry smk_per_100k if year==2010, robust
outreg2 using regression.doc, replace ctitle(Model 1)
reg emp_industry smk_per_100k urban_share poverty_rate literacy_15up ln_pop if year==2010, robust
outreg2 using employment.doc, append ctitle(Model 2)

twoway (scatter ln_gdppc smk_per_100k if year==2010, mcolor(navy%60)) ///
       (lfit ln_gdppc smk_per_100k if year==2010, lcolor(navy)), ///
    legend(off) ytitle("ln(GDP per capita)") xtitle("SMK per 100k population") ///
    title("2010 cross-section")
graph export "Result/Regresi 1.jpg", replace width(1400)

avplot smk_per_100k, ///
    ytitle("ln(GDP per capita) | controls") ///
    xtitle("SMK per 100k | controls") ///
    title("Partial regression: SMK vs GDP per capita, 2010")
graph export "Result/avplot_smk.jpg", replace width(1400)

rvfplot, yline(0) title("Residual vs fitted, 2010")
graph export "Result/Residual_vs_fitted.jpg", replace width(1400)