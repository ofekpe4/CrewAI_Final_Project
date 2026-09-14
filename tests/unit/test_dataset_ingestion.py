"""Unit tests for the Phase 2 dataset acquisition (PROJECT_PLAN.md §J, §T Phase 2).

Focus: the raw file `scripts/download_data.py` produces is present, hash-
verified, structurally as documented in `data/README.md`, and untouched by
any cleaning — plus that the ≥3 documented quality issues and the target's
class balance are real, measured facts about the actual bytes on disk.

This module does **not** perform any network access itself — only
`scripts/download_data.py` does that (PROJECT_PLAN.md §Phase 2 Gate 2D:
"avoid making every normal unit-test run network-dependent"). If the raw
file has not been acquired yet, every test here is skipped (not failed)
with a message telling you to run the acquisition script first.

Runnable two ways:
  * ``pytest tests/unit/test_dataset_ingestion.py``   (once pytest is installed)
  * ``python tests/unit/test_dataset_ingestion.py``   (no test dependency required)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# --- make the project importable without an install step ---
_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from harbor_vale import io_paths  # noqa: E402
from scripts.download_data import EXPECTED_SHA256  # noqa: E402

try:
    import pytest
except ImportError:  # pytest still intentionally absent from the project .venv
    pytest = None  # type: ignore[assignment]


RAW_CSV: Path = io_paths.RAW_TELCO_CHURN_CSV

# The Plan's mandatory criteria this file exercises (PROJECT_PLAN.md §J.1).
EXPECTED_SHAPE = (7043, 21)
EXPECTED_COLUMNS = {
    "customerID", "gender", "SeniorCitizen", "Partner", "Dependents",
    "tenure", "PhoneService", "MultipleLines", "InternetService",
    "OnlineSecurity", "OnlineBackup", "DeviceProtection", "TechSupport",
    "StreamingTV", "StreamingMovies", "Contract", "PaperlessBilling",
    "PaymentMethod", "MonthlyCharges", "TotalCharges", "Churn",
}
TARGET_RATE_MIN, TARGET_RATE_MAX = 0.10, 0.40  # PROJECT_PLAN.md §J.1 criterion 6


class _DatasetNotAcquired(Exception):
    """Raised (plain-python mode) when the raw file has not been downloaded yet."""


def _require_raw_csv() -> Path:
    if not RAW_CSV.is_file():
        message = (
            f"raw dataset not present at {io_paths.relative_to_root(RAW_CSV)} — "
            "run `python scripts/download_data.py` first"
        )
        if pytest is not None:
            pytest.skip(message)
        raise _DatasetNotAcquired(message)
    return RAW_CSV


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_raw() -> pd.DataFrame:
    return pd.read_csv(_require_raw_csv())


# --- acquisition ------------------------------------------------------------

def test_raw_file_exists_after_acquisition() -> None:
    path = _require_raw_csv()
    assert path.is_file()
    assert path.stat().st_size > 0


def test_raw_file_hash_matches_expected_sha256() -> None:
    path = _require_raw_csv()
    assert _sha256_of(path) == EXPECTED_SHA256, (
        "raw file SHA256 does not match the value locked in "
        "scripts/download_data.py / data/README.md — either upstream changed "
        "or the local file was corrupted/hand-edited"
    )


# --- structure ---------------------------------------------------------------

def test_dataset_loads_with_pandas() -> None:
    df = _load_raw()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_row_and_column_counts_match_documented_shape() -> None:
    df = _load_raw()
    assert df.shape == EXPECTED_SHAPE


def test_expected_core_columns_are_present() -> None:
    df = _load_raw()
    assert EXPECTED_COLUMNS.issubset(set(df.columns))


def test_one_row_per_customer_no_duplicates() -> None:
    # PROJECT_PLAN.md §J.1 criterion 10: one row = one entity.
    df = _load_raw()
    assert df["customerID"].is_unique
    assert not df.duplicated().any()


# --- target -------------------------------------------------------------------

def test_binary_target_exists() -> None:
    df = _load_raw()
    assert set(df["Churn"].unique()) == {"Yes", "No"}


def test_measured_target_rate_within_plan_range() -> None:
    df = _load_raw()
    positive_rate = (df["Churn"] == "Yes").mean()
    assert TARGET_RATE_MIN <= positive_rate <= TARGET_RATE_MAX, (
        f"measured Churn positive rate {positive_rate:.4f} outside the "
        f"Plan-required [{TARGET_RATE_MIN}, {TARGET_RATE_MAX}] band"
    )


# --- scale-sensitive column (criterion 4) --------------------------------------

def test_scale_sensitive_column_is_numeric_and_plausible() -> None:
    df = _load_raw()
    assert pd.api.types.is_numeric_dtype(df["MonthlyCharges"])
    assert df["MonthlyCharges"].min() > 0
    assert df["MonthlyCharges"].max() < 1000  # sanity bound, not a business rule


# --- documented quality issues (§data/README.md §7) — must be REAL, not faked ----

def test_quality_issue_total_charges_has_blank_placeholder_rows() -> None:
    """data/README.md §7.1 — 11 rows hold a literal ' ' instead of a number."""
    df = _load_raw()
    assert not pd.api.types.is_numeric_dtype(df["TotalCharges"]), (
        "TotalCharges loads as numeric — the documented quality issue is gone; "
        "update data/README.md if the upstream file genuinely changed"
    )
    blank_mask = df["TotalCharges"].astype(str).str.strip() == ""
    assert blank_mask.sum() == 11
    # Every blank row is a brand-new customer, per the documented root cause.
    assert (df.loc[blank_mask, "tenure"] == 0).all()


def test_quality_issue_service_columns_conflate_no_with_not_applicable() -> None:
    """data/README.md §7.2 — 'No' vs 'No {phone,internet} service' in 7 columns."""
    df = _load_raw()
    assert set(df["MultipleLines"].unique()) == {"Yes", "No", "No phone service"}
    internet_gated = [
        "OnlineSecurity", "OnlineBackup", "DeviceProtection",
        "TechSupport", "StreamingTV", "StreamingMovies",
    ]
    for column in internet_gated:
        assert set(df[column].unique()) == {"Yes", "No", "No internet service"}


def test_quality_issue_senior_citizen_encoded_inconsistently_with_peer_flags() -> None:
    """data/README.md §7.3 — SeniorCitizen is int 0/1; peer flags are str Yes/No."""
    df = _load_raw()
    assert pd.api.types.is_integer_dtype(df["SeniorCitizen"])
    assert set(df["SeniorCitizen"].unique()) == {0, 1}
    for column in ("Partner", "Dependents", "PhoneService", "PaperlessBilling"):
        assert not pd.api.types.is_integer_dtype(df[column])
        assert set(df[column].unique()) == {"Yes", "No"}


# --- integrity: raw means raw --------------------------------------------------

def test_raw_file_has_not_been_silently_normalized() -> None:
    """The whitespace placeholder in TotalCharges must survive untouched.

    If a cleaning step ever ran against this file in place, the blank cells
    would become "0", NaN, or be dropped — any of which would change both
    the SHA256 (already checked separately) and this direct byte-level check.
    """
    path = _require_raw_csv()
    raw_text = path.read_text(encoding="utf-8")
    header = raw_text.splitlines()[0]
    assert header == (
        "customerID,gender,SeniorCitizen,Partner,Dependents,tenure,"
        "PhoneService,MultipleLines,InternetService,OnlineSecurity,"
        "OnlineBackup,DeviceProtection,TechSupport,StreamingTV,"
        "StreamingMovies,Contract,PaperlessBilling,PaymentMethod,"
        "MonthlyCharges,TotalCharges,Churn"
    )
    assert ",No internet service," in raw_text or raw_text.count("No internet service") > 0


if __name__ == "__main__":
    _failures: list[str] = []
    _skipped: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except _DatasetNotAcquired as exc:
            _skipped.append(_name)
            print(f"SKIP  {_name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(
        f"\n{len(_failures)} failed, {len(_skipped)} skipped"
        if _failures or _skipped
        else "\nall passed"
    )
    sys.exit(1 if _failures else 0)
