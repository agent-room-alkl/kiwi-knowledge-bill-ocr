# -*- coding: utf-8 -*-
"""Re-export of the calc engine that actually ships.

There used to be two byte-identical copies of this module: this one, which the
tests imported, and `function_app/compute_summary.py`, which the Function App
deploys. Identical copies drift the moment someone edits one of them — and the
failure is silent in the worst direction, because the tests keep passing
against a file that is not the file in production.

One source of truth: the deployed module. Import it from here so
`from pipeline.compute_summary import ...` exercises exactly what ships.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "function_app"))

from compute_summary import *  # noqa: F401,F403,E402
from compute_summary import (  # noqa: F401,E402  - explicit for static checkers
    RECOMMENDED,
    SAVINGS_GIVING,
    INCOME,
    EXCLUSIONS,
    compute_summary,
    detect_frequency,
    monthly_equivalent,
    parse_date,
)
