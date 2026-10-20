"""CRA T4127 (2026 edition) payroll deduction constants — Ontario.

RULE: Every value here is transcribed from the T4127 PDF in `docs/` and carries
a comment citing the exact section/table/variable it came from. Nothing is
filled in from memory. If a required value is not found in the PDF, it stays
`PENDING` and we stop and ask — we do not guess.

This module is intentionally unfilled until the T4127 PDF is available (Phase 3).
Each constant below names what we need and where it comes from. Replace each
`PENDING` with the transcribed Decimal value (as `Decimal("...")`) and the
precise citation.
"""

from decimal import Decimal  # noqa: F401  (used once values are filled in)


class _Pending:
    """Sentinel for an untranscribed constant.

    Any arithmetic use raises, so the deduction code cannot silently run with a
    missing value — it fails loudly until the real T4127 figure is filled in.
    """

    def __repr__(self) -> str:
        return "PENDING(fill from T4127)"

    def _fail(self, *_a, **_k):
        raise NotImplementedError(
            "T4127 constant not yet transcribed. Add the T4127 PDF to docs/ and "
            "fill in livepay/tax/constants_2026.py with a cited value."
        )

    __add__ = __radd__ = __sub__ = __rsub__ = _fail
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _fail
    __lt__ = __le__ = __gt__ = __ge__ = _fail


PENDING = _Pending()

# --- CPP / CPP2 (T4127, "Canada Pension Plan" section) ---------------------
CPP_BASIC_EXEMPTION_ANNUAL = PENDING  # annual basic exemption
CPP_MAX_PENSIONABLE_EARNINGS = PENDING  # YMPE (first ceiling)
CPP_RATE = PENDING  # employee base contribution rate
CPP_MAX_CONTRIBUTION_ANNUAL = PENDING  # max base contribution
CPP2_MAX_ADDITIONAL_EARNINGS = PENDING  # YAMPE (second ceiling)
CPP2_RATE = PENDING  # CPP2 contribution rate
CPP2_MAX_CONTRIBUTION_ANNUAL = PENDING  # max CPP2 contribution

# --- Employment Insurance (T4127, "Employment Insurance" section) ----------
EI_RATE = PENDING  # employee EI premium rate
EI_MAX_INSURABLE_EARNINGS = PENDING  # annual max insurable earnings
EI_MAX_PREMIUM_ANNUAL = PENDING  # annual max EI premium

# --- Federal income tax (T4127 "Factor T1"; federal rate/threshold table) --
FEDERAL_TAX_BRACKETS = PENDING  # list of (upper_limit, rate)
FEDERAL_CONSTANT_K = PENDING  # per-bracket "K" constants
FEDERAL_BPA = PENDING  # basic personal amount (claim 1)
FEDERAL_LOWEST_RATE = PENDING  # rate for crediting BPA/CPP/EI

# --- Ontario income tax (T4127 Ontario "Factor T2"; surtax; health premium) -
ONTARIO_TAX_BRACKETS = PENDING  # list of (upper_limit, rate)
ONTARIO_CONSTANT_K = PENDING  # per-bracket "K" constants
ONTARIO_BPA = PENDING  # Ontario basic personal amount
ONTARIO_LOWEST_RATE = PENDING  # rate for crediting BPA/CPP/EI
ONTARIO_SURTAX_THRESHOLD_1 = PENDING  # first surtax threshold (V1)
ONTARIO_SURTAX_RATE_1 = PENDING  # first surtax rate
ONTARIO_SURTAX_THRESHOLD_2 = PENDING  # second surtax threshold
ONTARIO_SURTAX_RATE_2 = PENDING  # second surtax rate
ONTARIO_HEALTH_PREMIUM_BANDS = PENDING  # income bands -> premium amounts
