"""Unit tests — `harbor_vale.demo.fault_injection` (PROJECT_PLAN.md §O.3).

Focus here is the helpers' own safety/correctness contract — that they never
touch their source file, are deterministic, and produce the specific
mutation they claim to. What each mutation is DETECTED as by the gate is
covered per-family in `test_validator_*.py`.

Runnable two ways:
  * ``pytest tests/unit/test_fault_injection.py``
  * ``python tests/unit/test_fault_injection.py``
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from harbor_vale.demo import fault_injection as fi  # noqa: E402
from tests.fixtures.gate_fixtures import CONTRACT_JSON, FIXTURE_CSV  # noqa: E402


# --- never corrupts the source ---------------------------------------------------

def test_scale_change_never_writes_back_onto_its_source() -> None:
    original = FIXTURE_CSV.read_bytes()
    try:
        fi.scale_change(FIXTURE_CSV, FIXTURE_CSV, column="monthly_charges")
    except fi.FaultInjectionError:
        pass
    else:
        raise AssertionError("expected FaultInjectionError when out_path == source_path")
    assert FIXTURE_CSV.read_bytes() == original


def test_corrupt_contract_json_never_writes_back_onto_its_source() -> None:
    original = CONTRACT_JSON.read_bytes()
    try:
        fi.corrupt_contract_json(CONTRACT_JSON, CONTRACT_JSON)
    except fi.FaultInjectionError:
        pass
    else:
        raise AssertionError("expected FaultInjectionError when out_path == source_path")
    assert CONTRACT_JSON.read_bytes() == original


def test_every_helper_leaves_the_committed_fixtures_byte_identical() -> None:
    """Run the full O.3 helper set against the real fixtures and confirm
    both committed files are untouched afterward."""
    csv_before = FIXTURE_CSV.read_bytes()
    contract_before = CONTRACT_JSON.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fi.scale_change(FIXTURE_CSV, tmp_path / "1.csv", column="monthly_charges")
        fi.rename_column(FIXTURE_CSV, tmp_path / "2.csv", old_name="gender", new_name="sex")
        fi.drop_required_column(FIXTURE_CSV, tmp_path / "3.csv", column="monthly_charges")
        fi.change_dtype(FIXTURE_CSV, tmp_path / "4.csv", column="monthly_charges", dtype="int64")
        fi.inject_nulls(FIXTURE_CSV, tmp_path / "5.csv", column="contract_type", count=2)
        fi.unknown_category(FIXTURE_CSV, tmp_path / "6.csv", column="internet_service", new_value="Satellite")
        fi.flip_target_encoding(FIXTURE_CSV, tmp_path / "7.csv", target_column="churn")
        fi.truncate_dataset(FIXTURE_CSV, tmp_path / "8.csv", keep_rows=5)
        fi.corrupt_contract_json(CONTRACT_JSON, tmp_path / "9.json")
        fi.contract_only_change(CONTRACT_JSON, tmp_path / "10.json", drop_column="gender")
    assert FIXTURE_CSV.read_bytes() == csv_before
    assert CONTRACT_JSON.read_bytes() == contract_before


# --- determinism -----------------------------------------------------------------

def test_scale_change_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out1 = fi.scale_change(FIXTURE_CSV, tmp_path / "a.csv", column="monthly_charges")
        out2 = fi.scale_change(FIXTURE_CSV, tmp_path / "b.csv", column="monthly_charges")
        assert out1.read_bytes() == out2.read_bytes()


def test_truncate_dataset_is_deterministic_and_keeps_the_first_n_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.truncate_dataset(FIXTURE_CSV, Path(tmp) / "t.csv", keep_rows=7)
        full = pd.read_csv(FIXTURE_CSV)
        truncated = pd.read_csv(out)
    assert len(truncated) == 7
    assert (truncated["customer_id"].values == full["customer_id"].values[:7]).all()


# --- exact mutation content --------------------------------------------------------

def test_scale_change_multiplies_only_the_named_column() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.scale_change(FIXTURE_CSV, Path(tmp) / "s.csv", column="monthly_charges", factor=100.0)
        before = pd.read_csv(FIXTURE_CSV)
        after = pd.read_csv(out)
    assert (after["monthly_charges"] == before["monthly_charges"] * 100.0).all()
    assert (after["total_charges"] == before["total_charges"]).all()
    assert str(after["monthly_charges"].dtype) == "float64"


def test_inject_nulls_nulls_exactly_the_requested_count_deterministically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.inject_nulls(FIXTURE_CSV, Path(tmp) / "n.csv", column="contract_type", count=4)
        df = pd.read_csv(out)
    assert int(df["contract_type"].isnull().sum()) == 4
    assert df["contract_type"].isnull().tolist()[:4] == [True, True, True, True]


def test_flip_target_encoding_swaps_every_label() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = fi.flip_target_encoding(FIXTURE_CSV, Path(tmp) / "f.csv", target_column="churn")
        before = pd.read_csv(FIXTURE_CSV)["churn"]
        after = pd.read_csv(out)["churn"]
    assert (after == (1 - before)).all()


def test_corrupt_contract_json_produces_unparseable_json() -> None:
    import json

    with tempfile.TemporaryDirectory() as tmp:
        out = fi.corrupt_contract_json(CONTRACT_JSON, Path(tmp) / "bad.json")
        try:
            json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("expected the corrupted contract JSON to fail to parse")


# --- error handling ----------------------------------------------------------------

def test_scale_change_on_a_nonexistent_column_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            fi.scale_change(FIXTURE_CSV, Path(tmp) / "x.csv", column="not_a_real_column")
        except fi.FaultInjectionError:
            pass
        else:
            raise AssertionError("expected FaultInjectionError for an unknown column")


def test_contract_only_change_refuses_a_referenced_column() -> None:
    """`customer_id` is the primary key — removing it would break the
    contract's own self-consistency rules for reasons unrelated to this
    scenario; the helper must refuse rather than produce a broken contract."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            fi.contract_only_change(CONTRACT_JSON, Path(tmp) / "c.json", drop_column="customer_id")
        except fi.FaultInjectionError:
            pass
        else:
            raise AssertionError("expected FaultInjectionError for a primary-key column")


if __name__ == "__main__":
    _failures: list[str] = []
    for _name, _fn in sorted(
        (n, f) for n, f in dict(globals()).items() if n.startswith("test_") and callable(f)
    ):
        try:
            _fn()
        except Exception as exc:  # noqa: BLE001
            _failures.append(_name)
            print(f"FAIL  {_name}: {exc.__class__.__name__}: {exc}")
        else:
            print(f"PASS  {_name}")
    print(f"\n{len(_failures)} failed" if _failures else "\nall passed")
    sys.exit(1 if _failures else 0)
