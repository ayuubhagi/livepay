# docs/

Reference material. **Source PDFs are not committed** (see `.gitignore`) — they
are large and we should not redistribute a government document. Keep them here
locally so the citations in `livepay/tax/constants_2026.py` can be verified.

## What to put here

- **`t4127-jan-2026.pdf`** — CRA *Payroll Deductions Formulas (T4127), 116th
  Edition, effective January 1, 2026*. Download from canada.ca. Every tax
  constant in the code cites a section or table number from this document.

If a value we need is not in the PDF, the code stops and asks rather than
guessing.
