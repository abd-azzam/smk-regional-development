*=============================================================================
* smk_openings_models.do
*
* What determines where and when new SMK (vocational upper-secondary schools)
* open in Indonesian districts?
*
* Outcome  : open_smk_total  (count of new SMK opened in a district-year)
* Estimator: conditional fixed-effects Poisson  (xtpoisson ..., fe)
* Sample   : 321 districts on constant year-2000 borders
*
* WHY POISSON AND NOT OLS: the outcome is a count that is exactly zero in 59%
* of district-years (84% for public schools). See docs\descriptive_check.log.
* Reasons are set out in docs\smk_openings_explained.txt.
*
* This file ESTIMATES. Everything before it (descriptive_check.do) did not.
* It still never saves over dapoer_wide.dta.
*=============================================================================

clear all
set more off
cd "C:\Users\HP\Documents\UIII\Research Project\Pak Siro - MORA\data\DAPOER"
capture log close
log using "smk_openings_models.log", replace text

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

*=============================================================================
* 1. BUILD THE ANALYSIS VARIABLES
*=============================================================================

* --- labour demand. Use the SHARE, not the headcount: ln(emp_industry) and
*     ln(population) correlate 0.86, so the headcount is largely a size proxy.
generate double emp_share_industry = 100 * emp_industry / emp_total
label var emp_share_industry "Industry share of employment (%)"

generate double emp_share_agri = 100 * emp_agriculture / emp_total
label var emp_share_agri "Agriculture share of employment (%)"

* --- manufacturing intensity of output (SNA-2008 series only, 2010 onward)
generate double mfg_share_gdp = 100 * gdp_manufacturing_sna08 / gdp_constant_sna08
label var mfg_share_gdp "Manufacturing share of GDP (%)"

* --- fiscal capacity, per capita. Nominal IDR is fine here ONLY because i.year
*     absorbs the common inflation path; the cross-district comparison is what
*     identifies the coefficient. Do not read these as real values.
generate double rev_pc = revenue_total / population
generate double edu_pc = expenditure_education / population
generate double ln_rev_pc = ln(rev_pc)
generate double ln_edu_pc = ln(edu_pc)
label var ln_rev_pc "ln total revenue per capita (nominal)"
label var ln_edu_pc "ln education spending per capita (nominal)"

* --- fiscal COMPOSITION, not level. DAU is the general allocation grant and is
*     about two thirds of a district budget, so ln(dau_pc) would be almost the
*     same variable as ln_rev_pc. Use shares instead: they say where the money
*     comes from without repeating how much of it there is.
*     dau_share  = dependence on central transfers
*     osr_share  = local tax effort / fiscal autonomy
* --- resource dependence. The closest thing this data has to an "extractive"
*     measure: revenue that arrives from natural-resource rents rather than from
*     taxing residents. Read the caveat in section 3b before using it.
generate double res_share = 100 * revenue_dbh_sda_total / revenue_total
label var res_share "Natural-resource revenue as % of total revenue"

generate double dau_share = 100 * revenue_dau / revenue_total
generate double osr_share = 100 * revenue_own_source / revenue_total
label var dau_share "DAU as % of total revenue (central transfer dependence)"
label var osr_share "Own-source revenue as % of total (local tax effort)"

* --- urbanisation. Use SUSENAS: urban_share has only ~1,700 observations.
*     The 0-1 to 0-100 rescale now happens in the build script, not here.
generate double urban_pct = urban_share_susenas
label var urban_pct "Urban share of population (%), SUSENAS"

* --- feeder pipeline: you cannot fill an SMK without SMP graduates
label var enrollment_junior_secondary "Net enrolment ratio, junior secondary (%)"

* --- rates above 100 are already set to missing by the build script. Assert
*     that rather than assume it: a failure here means a stale dapoer_wide.
foreach v in enrollment_junior_secondary enrollment_senior_secondary ///
             literacy_15up poverty_rate urban_pct {
    quietly count if `v' > 100 & !missing(`v')
    if r(N) > 0 {
        display as error "STOP: `v' still has " r(N) " values above 100. Rebuild from CSV."
        exit 459
    }
}

*=============================================================================
* 2. DEFINE THE SAMPLE
*
* Main sample ends in 2016. Law 23/2014 moved authority over senior secondary
* schools from districts to provinces with effect from 2016-17, and the opening
* counts collapse from 672 (2016) to 263 (2017). After that the district is no
* longer the body deciding to open a school, so a district-level determinants
* model is answering a different question. Full sample is run as robustness.
*=============================================================================

generate byte insample = !missing(open_smk_total) & inrange(year, 1996, 2016)
label var insample "Main estimation window"

tabulate year if insample & !missing(open_smk_total)
summarize open_smk_total open_SMK_negeri open_SMK_swasta if insample, detail

* how many districts never open a single school in the window? Conditional
* fixed-effects Poisson silently drops them - they carry no within information.
preserve
    keep if insample
    collapse (max) mx = open_smk_total, by(unit)
    count
    local ntot = r(N)
    count if mx == 0
    display "districts with ZERO openings in window (dropped by FE Poisson): " r(N) " of " `ntot'
restore

*=============================================================================
* 3. MAIN LADDER - each model adds controls and LOSES years.
*
* Read the N on every line. emp_share_industry only exists from 2007, and
* mfg_share_gdp only from 2010, so models 4 and 5 are different samples, not
* just different specifications. Compare 4 against 3 re-run on model 4's sample
* before concluding that adding employment changed anything.
*
* exposure(population) puts ln(population) in with its coefficient fixed at 1,
* so the models explain openings PER PERSON rather than raw counts. That is the
* right normalisation for a count outcome and it keeps population out of the
* collinearity problem entirely.
*=============================================================================

eststo clear

* M1 - baseline: demographics only
eststo m1: xtpoisson open_smk_total poverty_rate urban_pct i.year ///
    if insample, fe exposure(population) vce(robust)

* M2 - add fiscal capacity
eststo m2: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share i.year ///
    if insample, fe exposure(population) vce(robust)

* M3 - add the schooling pipeline
eststo m3: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary i.year ///
    if insample, fe exposure(population) vce(robust)

* M4 - add labour demand. NOTE: 2007 onward only.
eststo m4: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary emp_share_industry i.year ///
    if insample, fe exposure(population) vce(robust)

* Mark exactly which rows M4 used, so the next model can be run on the same ones.
capture drop m4samp
generate byte m4samp = e(sample)

* M4b - M3's specification on M4's sample. Without this you cannot tell whether
* a change from M3 to M4 came from adding employment or from losing 1996-2006.
eststo m4b: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary i.year ///
    if m4samp, fe exposure(population) vce(robust)

* M5 - add manufacturing intensity. NOTE: 2010 onward only, very short.
eststo m5: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share osr_share enrollment_junior_secondary ///
    emp_share_industry mfg_share_gdp i.year ///
    if insample, fe exposure(population) vce(robust)

*=============================================================================
* 3b. RESOURCE DEPENDENCE  ("extractive institutions")
*
* READ THIS BEFORE INTERPRETING M6.
*
* Institutions in the Acemoglu-Robinson sense are slow-moving. Anything that is
* fixed within a district across 1996-2016 is ABSORBED BY THE DISTRICT FIXED
* EFFECT and cannot be estimated here at all. So this is NOT a test of
* extractive institutions. What res_share actually measures is the year-to-year
* flow of natural-resource revenue, which moves with commodity prices.
* Call it resource dependence in the write-up, not institutions.
*
* Two reasons it is still worth including:
*   (a) as a confounder - resource districts are less industrial AND may invest
*       differently in schooling, so it could bias emp_share_industry;
*   (b) osr_share is the other side of the same idea - a district that raises
*       its own taxes has to answer to the people it taxes.
*
* Cost: res_share exists for about 1,186 of M4's 2,109 rows, so M6 runs on
* roughly half of M4. Compare M6 against M6b, not against M4.
*=============================================================================

eststo m6: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary ///
    emp_share_industry res_share osr_share i.year ///
    if insample, fe exposure(population) vce(robust)

capture drop m6samp
generate byte m6samp = e(sample)

* M6b - M4's specification on M6's rows, so you can tell whether a change came
* from adding resource dependence or from losing half the sample.
eststo m6b: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary ///
    emp_share_industry i.year ///
    if m6samp, fe exposure(population) vce(robust)

* within variation, so you can see FE has something to work with
xtsum res_share osr_share if insample

*=============================================================================
* 3c. CONFOUNDERS - what to add, and what to TAKE OUT
*
* "Control for anything that might conflate it" is the wrong instinct in a fixed
* effects model, for three reasons:
*
*   (1) District FE already absorbs every confounder that does not move over
*       time. Geography, colonial history, distance to Java, ethnic composition
*       - all gone already. Only time-VARYING confounders can bias anything.
*       n_children has within/overall = 0.00, which is why it cannot be a control.
*
*   (2) A control that is itself CAUSED by industry makes the bias worse, not
*       better (the "bad control" problem). If industry raises the tax base and
*       lowers poverty, then holding revenue and poverty fixed removes part of
*       the very channel you are trying to measure.
*
*   (3) Every control costs sample. M4 is already 2,036 rows on 283 districts.
*
* So this section does BOTH directions: M7 adds the controls that are free and
* defensible, M8 takes out the ones that are probably bad controls.
*
* Checked before choosing (coverage inside M4's sample, and within/overall):
*     enrollment_senior_secondary  100%   0.74
*     access_electricity           100%   0.58
*     literacy_15up                100%   0.40
*     skilled_birth_attendance     100%   0.68
*     hh_expenditure_pc             88%   0.89
*     revenue_dbh_sda_total         56%   0.64
*     schools_senior_secondary      28%   0.56   <- want it, cannot afford it
*     n_children                   100%   0.00   <- absorbed by FE, useless
*=============================================================================

* M7 - add the pre-determined controls that cost no sample at all.
*      access_electricity is infrastructure and mostly centrally funded, and
*      literacy_15up is a stock built up over earlier decades, so neither is
*      plausibly caused by this year's industrial employment.
eststo m7: xtpoisson open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary ///
    emp_share_industry access_electricity literacy_15up i.year ///
    if insample, fe exposure(population) vce(robust)

* M8 - PARSIMONIOUS. Drops poverty_rate and ln_rev_pc, which are the two most
*      likely bad controls: industry plausibly lowers poverty and raises the tax
*      base, so conditioning on them closes part of the path from industry to
*      school openings. Run on M4's rows so the comparison is like-for-like.
*      If emp_share_industry is going to appear anywhere, it is here.
eststo m8: xtpoisson open_smk_total urban_pct dau_share ///
    enrollment_junior_secondary emp_share_industry access_electricity ///
    literacy_15up i.year ///
    if m4samp, fe exposure(population) vce(robust)

* Is schools_senior_secondary (the existing stock) worth the sample it costs?
* Reported so you can see the trade rather than guess at it.
eststo m9: xtpoisson open_smk_total urban_pct dau_share ///
    enrollment_junior_secondary emp_share_industry schools_senior_secondary ///
    i.year if insample, fe exposure(population) vce(robust)

capture which esttab
if !_rc {
    esttab m1 m2 m3 m4 m4b m5 m6 m6b m7 m8 m9, ///
        keep(poverty_rate urban_pct ln_rev_pc ln_edu_pc dau_share osr_share ///
             res_share enrollment_junior_secondary emp_share_industry ///
             access_electricity literacy_15up schools_senior_secondary mfg_share_gdp) ///
        b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
        stats(N N_g, labels("Observations" "Districts")) ///
        title("Determinants of SMK openings - conditional FE Poisson, 1996-2016")
}
else display as error "esttab not installed. Run: ssc install estout"

*=============================================================================
* 4. PUBLIC vs PRIVATE
*
* These have different decision-makers. Public SMK follow central and district
* policy; private SMK follow local demand. Pooling them averages the mechanism
* away. Public openings are 84% zeros, so expect many districts to drop.
*=============================================================================

eststo clear

eststo pub: xtpoisson open_SMK_negeri poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary emp_share_industry i.year ///
    if insample, fe exposure(population) vce(robust)

eststo prv: xtpoisson open_SMK_swasta poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary emp_share_industry i.year ///
    if insample, fe exposure(population) vce(robust)

capture which esttab
if !_rc {
    esttab pub prv, b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
        keep(poverty_rate urban_pct ln_rev_pc ln_edu_pc dau_share ///
             enrollment_junior_secondary emp_share_industry) ///
        mtitles("Public (negeri)" "Private (swasta)") ///
        stats(N N_g, labels("Observations" "Districts"))
}

*=============================================================================
* 5. ROBUSTNESS
*=============================================================================

* 5a. Full window including the post-2017 regime. If results move, the 2017
*     authority transfer is doing the work, not your covariates.
xtpoisson open_smk_total poverty_rate urban_pct ln_rev_pc ln_edu_pc dau_share ///
    enrollment_junior_secondary emp_share_industry i.year ///
    if !missing(open_smk_total) & year >= 1996, ///
    fe exposure(population) vce(robust)

* 5b. Linear fixed effects on the same sample, for comparison ONLY.
*     Expect it to differ. A linear model on a 59%-zero outcome can predict
*     negative openings; it is here to show the difference, not as an estimate.
generate double open_pc = 100000 * open_smk_total / population
label var open_pc "SMK openings per 100,000 people"
xtreg open_pc poverty_rate urban_pct ln_rev_pc ln_edu_pc dau_share ///
    enrollment_junior_secondary emp_share_industry i.year ///
    if insample, fe vce(cluster unit)

* 5c. Negative binomial. CAVEAT: Stata's xtnbreg, fe is not a true fixed-effects
*     estimator in the usual sense (Allison & Waterman 2002) - it does not sweep
*     out a district-specific intercept the way xtpoisson, fe does. Read it as a
*     sensitivity check on the point estimates only, never as the main result.
capture noisily xtnbreg open_smk_total poverty_rate urban_pct ///
    ln_rev_pc ln_edu_pc dau_share enrollment_junior_secondary emp_share_industry i.year ///
    if insample, fe

* 5d. ppmlhdfe if available - same estimator, better with many fixed effects,
*     and it reports separation explicitly.
capture which ppmlhdfe
if !_rc {
    ppmlhdfe open_smk_total poverty_rate urban_pct ln_rev_pc ln_edu_pc dau_share ///
        enrollment_junior_secondary emp_share_industry ///
        if insample, absorb(unit year) exposure(population) vce(cluster unit)
}
else display as text "ppmlhdfe not installed (optional). ssc install ppmlhdfe"

*=============================================================================
* 6. WHAT TO WRITE DOWN
*=============================================================================
display _newline "{txt}Record from the output above:"
display "  1. N and number of districts on EVERY model - they are not the same sample"
display "  2. How many districts FE Poisson dropped for having no openings at all"
display "  3. Whether emp_share_industry survives when M4 is compared to M4b"
display "  4. Whether the public and private coefficients have the same sign"
display "  5. Whether 5a (full window) moves the coefficients materially"
display "  6. Whether res_share does anything, and M6 vs M6b before you believe it"
display "  7. Whether emp_share_industry moves in M8, the spec with the bad controls removed"

log close
