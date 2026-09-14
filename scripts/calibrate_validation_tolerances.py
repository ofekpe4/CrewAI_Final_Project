"""Calibration evidence for `config/settings.yaml`'s `validation:` block
(PROJECT_PLAN.md §V.2 N5, §U7 — "0.25 מכויל מול נתונים אמיתיים בשלב 4").

**What this script is NOT:** part of the validation gate, part of any
pipeline, or something `contract/validator.py` imports or calls. It is a
one-off, rerunnable analysis tool that produces the evidence behind two
numbers in `settings.yaml` — run manually, its output pasted into
`docs/validation_calibration.md`. Deterministic (`numpy.random.default_rng(42)`,
matching the seed already pinned in `settings.yaml` §R.1).

**What it measures:** this project has no real recurring "monthly batches"
— Phase 2 downloaded the real Telco Customer Churn dataset once
(`data/raw/telco_customer_churn.csv`, 7,043 rows). There is therefore no
repeated real-world draw to measure *actual* natural drift against. What
CAN be measured honestly from the real data: how much apparent drift pure
sampling noise alone produces, via bootstrap resampling at a range of
batch sizes — establishing a defensible upper bound on "how volatile could
this look with zero real problem", against which the chosen tolerances
(0.25 relative for `monthly_charges`' median, 0.05 absolute for `churn`'s
positive rate) can be honestly judged, without inventing a false claim
about real month-over-month variation this project's static dataset cannot
supply.

Usage:
    python scripts/calibrate_validation_tolerances.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from harbor_vale.io_paths import RAW_TELCO_CHURN_CSV  # noqa: E402

N_ITER = 3000
BATCH_SIZES = (100, 300, 700, 1500, 3500, 7043)
SEED = 42  # matches config/settings.yaml seeds.numpy


def _bootstrap_relative_deviation(series: "pd.Series", population_value: float, size: int, rng, statistic) -> "np.ndarray":
    replace = size >= len(series)
    devs = np.empty(N_ITER)
    for i in range(N_ITER):
        sample = series.sample(n=size, replace=replace, random_state=rng.integers(0, 2**32 - 1))
        devs[i] = abs(statistic(sample) - population_value)
    return devs


def main() -> int:
    if not RAW_TELCO_CHURN_CSV.is_file():
        print(
            f"ERROR: {RAW_TELCO_CHURN_CSV} not found — run scripts/download_data.py first.",
            file=sys.stderr,
        )
        return 1

    df = pd.read_csv(RAW_TELCO_CHURN_CSV)
    df["Churn01"] = (df["Churn"] == "Yes").astype(int)

    pop_median = float(df["MonthlyCharges"].median())
    pop_rate = float(df["Churn01"].mean())
    print(f"population n={len(df)}  median(MonthlyCharges)={pop_median:.4f}  churn_rate={pop_rate:.4f}\n")

    rng = np.random.default_rng(SEED)
    print(f"{'batch_n':>8} {'p50 median-dev%':>17} {'p95 median-dev%':>17} {'p99 median-dev%':>17} {'max median-dev%':>17}")
    for size in BATCH_SIZES:
        devs = _bootstrap_relative_deviation(df["MonthlyCharges"], pop_median, size, rng, lambda s: s.median())
        devs_pct = devs / pop_median * 100
        print(f"{size:8d} {np.percentile(devs_pct,50):17.3f} {np.percentile(devs_pct,95):17.3f} {np.percentile(devs_pct,99):17.3f} {devs_pct.max():17.3f}")

    print(f"\n{'batch_n':>8} {'p50 rate-dev(pp)':>17} {'p95 rate-dev(pp)':>17} {'p99 rate-dev(pp)':>17} {'max rate-dev(pp)':>17}")
    for size in BATCH_SIZES:
        devs = _bootstrap_relative_deviation(df["Churn01"], pop_rate, size, rng, lambda s: s.mean())
        devs_pp = devs * 100
        print(f"{size:8d} {np.percentile(devs_pp,50):17.3f} {np.percentile(devs_pp,95):17.3f} {np.percentile(devs_pp,99):17.3f} {devs_pp.max():17.3f}")

    print("\nIncident-scale deviations for reference (deliberate corruption, not sampling noise):")
    for factor in (2, 3, 10, 100):
        dev = abs(pop_median * factor - pop_median) / pop_median * 100
        print(f"  x{factor:<4} median deviation: {dev:.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
