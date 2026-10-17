"""osp-qa (layer L3): simulation report and distribution checks. Pure. See README.md."""

from .report import BALANCE_ALPHA, REPORT_FORMAT, build_report
from .stats import ChiSquare, chi2_sf, chi_square, gamma_q

__all__ = [
    "BALANCE_ALPHA",
    "REPORT_FORMAT",
    "ChiSquare",
    "build_report",
    "chi2_sf",
    "chi_square",
    "gamma_q",
]
