# Filling in the PDOC expected values

Phase 4 proves our deduction engine matches the CRA **Payroll Deductions Online
Calculator (PDOC)** to the cent. The inputs are in `tests/fixtures/pdoc_cases.csv`;
you fill in the expected (`exp_*`) columns from PDOC. I must not fill these in —
that would defeat the point of an independent check.

## Steps

1. Open PDOC: https://apps.cra-arc.gc.ca/ebci/rhpd/ (choose **Salary**, 2026).
2. For each row in the CSV, enter:
   - **Pay period frequency:** Biweekly (26 pay periods a year).
   - **Province of employment:** Ontario.
   - **Gross income this period:** the `gross` column.
   - **Federal / provincial claim codes:** `federal_claim_code` /
     `ontario_claim_code`.
   - **Year-to-date amounts:** enter `ytd_cpp`, `ytd_cpp2`, and `ytd_ei` in the
     corresponding "deducted year-to-date" fields so the annual maximums apply.
3. Read back and record, to the cent:
   - `exp_cpp` — CPP (base) contribution
   - `exp_cpp2` — CPP2 (second additional) contribution
   - `exp_ei` — EI premium
   - `exp_fed_tax` — federal income tax
   - `exp_on_tax` — Ontario income tax (this should already include the Ontario
     surtax and the Ontario Health Premium — confirm PDOC's breakdown)
   - `exp_net` — net pay

## Notes

- **Cases 16–22 are the maximum/limit tests.** The YTD numbers I pre-filled are
  rough; if PDOC rejects a value or you want the cap to trigger exactly at the
  boundary, replace the YTD with the real 2026 annual maximum from the T4127
  tables, and record whatever PDOC returns. The test only requires that our code
  and PDOC use the *same* inputs — so adjust the input if needed, just keep both
  sides consistent.
- If PDOC splits Ontario tax, surtax, and the Health Premium into separate
  lines, record their **sum** in `exp_on_tax` (we'll compare the combined
  provincial deduction). We can split later if useful.
- Leave a row's expected cells blank only if you skip it; Phase 4 will simply
  not parametrize blank rows.
