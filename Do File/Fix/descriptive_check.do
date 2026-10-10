*=============================================================================
* descriptive_check.do
* Screen every variable in dapoer_wide.dta before using it in anything.
* Run top to bottom, then read descriptive_check.log.
* Nothing here estimates anything.
*=============================================================================

clear all
set more off
cd "C:\Users\HP\Documents\UIII\Research Project\Pak Siro - MORA\data\DAPOER"
capture log close
log using "descriptive_check.log", replace text

use "dapoer_wide.dta", clear

* ---- GUARD: dapoer_wide.dta is a GENERATED file on constant year-2000 borders
* (341 units). This do-file NEVER saves. If a check fails, rebuild it with
*     python build_dapoer_2000borders.py
quietly count if missing(unit)
if r(N) > 0 | _N == 0 {
    display as error "STOP: no `unit' column. Rebuild dapoer_wide.dta."
    exit 459
}
quietly summarize unit, meanonly
if r(N) == 0 {
    display as error "STOP: dapoer_wide.dta looks wrong. Rebuild from the build script."
    exit 459
}
capture confirm variable ln_population
if !_rc {
    display as error "STOP: ln_* scratch variables are baked into the file. Rebuild."
    exit 459
}
quietly summarize dak_education, meanonly
if r(max) > 1e15 & !missing(r(max)) {
    display as error "STOP: dak_education looks rescaled twice. Rebuild."
    exit 459
}

xtset unit year

* Build the screening list. GLOBAL, not local, on purpose: locals die between
* separate `do` calls, so a local would come back empty if you run this file
* chunk-by-chunk from the editor (highlight + Ctrl+D). Every loop below uses $V.
* The two `local' lines must stay in this same block -- `: list' reads locals only,
* so a global on the right-hand side would silently subtract nothing.
unab ALL : _all
local IDS unit unit_name n_children year
local PROVONLY credit_manufacturing export_manufactured export_manufactured_misc ///
                import_manufactured import_manufactured_misc
local V : list ALL - IDS
local V : list V - PROVONLY
global V `V'
display "screening " `: word count $V' " variables"    // expect 94

*--- STEP 0. keys and shape ------------------------------------------------
isid unit year                  // must pass; if it fails, stop
xtdescribe

*--- STEP 1. missingness, and WHEN it is missing ----------------------------
misstable summarize $V

* first year, last year and N for every variable - the truncation trap
display _newline "{txt}variable{col 34}first{col 42}last{col 50}N"
foreach v of global V {
    quietly summarize year if !missing(`v')
    if r(N) > 0 {
        display as text %-32s "`v'" as result %6.0f r(min) %8.0f r(max) %10.0f r(N)
    }
    else display as error %-32s "`v'" "   EMPTY"
}

*--- STEP 2. range and impossible values -----------------------------------
* shares and rates must sit in [0,100]
foreach v in enrollment_primary enrollment_junior_secondary ///
             enrollment_senior_secondary literacy_15up poverty_rate ///
             urban_share rural_share urban_share_susenas morbidity_rate ///
             skilled_birth_attendance access_electricity access_water ///
             access_sanitation access_phone {
    quietly count if (`v' < 0 | `v' > 100) & !missing(`v')
    if r(N) > 0 display as error "`v': " r(N) " values outside [0,100]"
}

* counts and money must be non-negative
foreach v of global V {
    quietly count if `v' < 0
    if r(N) > 0 display as error "`v': " r(N) " negative values"
}

* urban + rural should be ~100
quietly generate double _urs = urban_share + rural_share
summarize _urs, detail
drop _urs

*--- STEP 3. zeros that are probably missing --------------------------------
foreach v of global V {
    quietly count if `v' == 0
    local z = r(N)
    quietly count if !missing(`v')
    if r(N) > 0 & `z'/r(N) > 0.10 ///
        display as error %-32s "`v'" "  zeros = " %5.1f 100*`z'/r(N) "% of nonmissing"
}

*--- STEP 4. distribution, outliers, skew -----------------------------------
foreach v of global V {
    display _newline as text "==== `v' ===="
    summarize `v', detail
}

* compact outlier screen: p99/p50 > 100 means a units problem, not a fat tail
display _newline "{txt}variable{col 34}p99/p50"
foreach v of global V {
    quietly summarize `v', detail
    if r(N) > 0 & r(p50) > 0 ///
        display as text %-32s "`v'" as result %12.1f r(p99)/r(p50)
}

*--- STEP 5. breaks over time ----------------------------------------------
* a real series drifts; a broken one jumps. Watch the count column too.
foreach v in gdp_constant_pre2010 gdp_constant_sna08 ///
             gdp_manufacturing_pre2010 gdp_manufacturing_sna08 ///
             revenue_total revenue_dak expenditure_education population emp_total {
    display _newline as text "==== median of `v' by year ===="
    preserve
        collapse (p50) m=`v' (count) n=`v', by(year)
        list year m n, noobs
    restore
}

* the known GDP splice: is the pre2010/sna08 ratio stable across districts?
preserve
    keep if inrange(year,2010,2013) & !missing(gdp_constant_pre2010, gdp_constant_sna08)
    generate double _ratio = gdp_constant_sna08 / gdp_constant_pre2010
    summarize _ratio, detail
restore

*--- STEP 6. within vs between (decides whether FE is viable) ---------------
xtsum $V

*--- STEP 7. components vs totals ------------------------------------------
quietly generate double _empsum = emp_agriculture + emp_industry + emp_mining + ///
    emp_construction + emp_utilities + emp_trade + emp_transport + ///
    emp_finance + emp_social_services
quietly generate double _empgap = 100*(_empsum - emp_total)/emp_total
summarize _empgap, detail

* Revenue, WITHOUT the two central transfers. Expect roughly -72%: that gap is
* what DAU and DAK account for, and it is the reason these three must never be
* presented as a decomposition of total revenue on their own.
quietly generate double _revsum3 = revenue_own_source + revenue_sharing + revenue_other
quietly generate double _revgap3 = 100*(_revsum3 - revenue_total)/revenue_total
summarize _revgap3, detail

* Revenue, WITH DAU and DAK. Expect roughly 0 - this is the real check.
quietly generate double _revsum = revenue_own_source + revenue_sharing + ///
    revenue_other + revenue_dau + revenue_dak
quietly generate double _revgap = 100*(_revsum - revenue_total)/revenue_total
summarize _revgap, detail

* how much of district revenue is a central transfer?
quietly generate double _dau_share = 100*revenue_dau/revenue_total
summarize _dau_share, detail

quietly generate double _daksum = dak_education + dak_health + dak_infrastructure + ///
    dak_agriculture + dak_environment + dak_forestry + dak_fishery + ///
    dak_government + dak_demographic + dak_trade + dak_village
quietly generate double _dakgap = 100*(_daksum - revenue_dak)/revenue_dak
summarize _dakgap, detail
drop _empsum _empgap _revsum3 _revgap3 _revsum _revgap _dau_share _daksum _dakgap

*--- STEP 8. collinearity among candidate predictors ------------------------
foreach v in population emp_total emp_industry revenue_total ///
             expenditure_education gdp_constant_sna08 gdp_manufacturing_sna08 {
    quietly generate double ln_`v' = ln(`v')
}
pwcorr ln_population ln_emp_total ln_emp_industry ln_revenue_total ///
       ln_expenditure_education ln_gdp_constant_sna08 ln_gdp_manufacturing_sna08 ///
       urban_share poverty_rate, obs

*--- STEP 9. the outcome: SMK openings --------------------------------------
* present for the 321 districts that match the panel's year-2000 borders
codebook open_smk_total open_SMK_negeri open_SMK_swasta, compact
summarize open_smk_total open_SMK_negeri open_SMK_swasta, detail
xtsum  open_smk_total open_SMK_negeri open_SMK_swasta

* how many district-years are actually usable
count if !missing(open_smk_total)
quietly levelsof unit if !missing(open_smk_total), local(HAVE)
display "districts with opening data: " `: word count `HAVE''

* openings by year - shows the policy expansion
preserve
    collapse (sum) open_smk_total open_SMK_negeri open_SMK_swasta, by(year)
    list, noobs
restore

log close
