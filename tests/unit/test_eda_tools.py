"""Unit tests — `tools/eda_tools.py` (PROJECT_PLAN.md §D.2).

Proves: measured stats are correct, evidence keys are stable, an invalid
`InsightsDoc.evidence_stat_key` is rejected, figures generate
deterministically, the report renders, the degraded/fallback banner
renders visibly, filenames are deterministic, and no LLM is needed
anywhere in this module.

Runnable two ways:
  * ``pytest tests/unit/test_eda_tools.py``
  * ``python tests/unit/test_eda_tools.py``
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

from harbor_vale.plans.insights_doc import Insight, InsightsDoc, validate_insights_doc  # noqa: E402
from harbor_vale.tools.eda_tools import (  # noqa: E402
    compute_eda_stats,
    compute_numeric_correlations,
    generate_numeric_distribution_figure,
    generate_target_rate_figure,
    render_eda_report_html,
    render_insights_markdown,
    sha256_of_file,
)


def _sample_df() -> "pd.DataFrame":
    return pd.DataFrame(
        {
            "monthly_charges": [20.0, 100.0, 60.0, 40.0, 80.0, 50.0, 30.0, 90.0],
            "contract_type": ["Month-to-month", "Two year", "Month-to-month", "One year",
                               "Two year", "Month-to-month", "One year", "Two year"],
            "churn": [1, 0, 1, 0, 0, 1, 0, 0],
        }
    )


# --- measured stats are correct ----------------------------------------------

def test_numeric_stats_match_direct_pandas_measurement() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    assert stats["monthly_charges.mean"] == float(df["monthly_charges"].mean())
    assert stats["monthly_charges.median"] == float(df["monthly_charges"].median())
    assert stats["monthly_charges.min"] == float(df["monthly_charges"].min())
    assert stats["monthly_charges.max"] == float(df["monthly_charges"].max())
    assert stats["monthly_charges.count"] == 8


def test_target_positive_rate_matches_direct_measurement() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    assert stats["churn.positive_rate"] == float(df["churn"].mean())
    assert stats["churn.positive_count"] == int(df["churn"].sum())


def test_target_rate_by_category_matches_direct_groupby() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    expected = df.groupby("contract_type")["churn"].mean()
    for category, rate in expected.items():
        assert stats[f"contract_type.target_rate_by_category.{category}"] == float(rate)


def test_dataset_level_stats() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    assert stats["dataset.row_count"] == len(df)
    assert stats["dataset.column_count"] == len(df.columns)


def test_correlations_are_symmetric_pair_not_duplicated() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    corr = compute_numeric_correlations(df)
    assert "x__vs__y" in corr
    assert "y__vs__x" not in corr
    assert abs(corr["x__vs__y"] - 1.0) < 1e-9


# --- evidence keys are stable / anti-hallucination ---------------------------

def test_evidence_stat_key_that_exists_is_accepted() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    doc = InsightsDoc(
        headline="test",
        insights=[
            Insight(title="t", observation="o", business_implication="b",
                    recommended_action="r", evidence_stat_key="monthly_charges.mean")
        ],
    )
    ok, result = validate_insights_doc(doc, eda_stats=stats)
    assert ok, result


def test_evidence_stat_key_that_does_not_exist_is_rejected() -> None:
    """The concrete anti-hallucination proof: a plausible-looking but
    nonexistent key must be rejected, not silently accepted."""
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    doc = InsightsDoc(
        headline="test",
        insights=[
            Insight(title="t", observation="o", business_implication="b",
                    recommended_action="r", evidence_stat_key="monthly_charges.invented_stat_that_does_not_exist")
        ],
    )
    ok, msg = validate_insights_doc(doc, eda_stats=stats)
    assert ok is False
    assert "evidence_stat_key" in msg


def test_evidence_stat_keys_are_stable_across_repeated_calls() -> None:
    df = _sample_df()
    stats1 = compute_eda_stats(df, target_column="churn")
    stats2 = compute_eda_stats(df, target_column="churn")
    assert set(stats1) == set(stats2)
    assert stats1 == stats2


# --- figures ------------------------------------------------------------------

def test_figures_are_generated() -> None:
    df = _sample_df()
    with tempfile.TemporaryDirectory() as tmp:
        fig1 = generate_target_rate_figure(df, column="contract_type", target_column="churn", out_dir=tmp)
        fig2 = generate_numeric_distribution_figure(df, column="monthly_charges", out_dir=tmp)
        assert fig1.is_file() and fig1.stat().st_size > 0
        assert fig2.is_file() and fig2.stat().st_size > 0


def test_figures_have_deterministic_filenames() -> None:
    df = _sample_df()
    with tempfile.TemporaryDirectory() as tmp:
        fig = generate_target_rate_figure(df, column="contract_type", target_column="churn", out_dir=tmp)
        assert fig.name == "target_rate_by__contract_type.png"
        fig2 = generate_numeric_distribution_figure(df, column="monthly_charges", out_dir=tmp)
        assert fig2.name == "distribution__monthly_charges.png"


def test_figures_are_byte_identical_given_the_same_data() -> None:
    df = _sample_df()
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        f1 = generate_target_rate_figure(df, column="contract_type", target_column="churn", out_dir=tmp1)
        f2 = generate_target_rate_figure(df, column="contract_type", target_column="churn", out_dir=tmp2)
        assert sha256_of_file(f1) == sha256_of_file(f2)


# --- report rendering -----------------------------------------------------------

def test_report_renders_with_a_valid_insights_doc() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    doc = InsightsDoc(
        headline="Contract type drives churn",
        insights=[
            Insight(title="t", observation="o", business_implication="b",
                    recommended_action="r", evidence_stat_key="churn.positive_rate")
        ],
        data_caveats=["small demo sample"],
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = render_eda_report_html(
            dataset_name="demo", stats=stats, figures=[], insights=doc, out_path=Path(tmp) / "eda_report.html"
        )
        text = out.read_text(encoding="utf-8")
    assert "Contract type drives churn" in text
    assert "Narrative unavailable" not in text
    assert "small demo sample" in text


def test_insights_markdown_renders_with_a_valid_insights_doc() -> None:
    doc = InsightsDoc(
        headline="Headline here",
        insights=[
            Insight(title="Title", observation="Obs", business_implication="Impl",
                    recommended_action="Action", evidence_stat_key="churn.positive_rate")
        ],
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = render_insights_markdown(dataset_name="demo", insights=doc, out_path=Path(tmp) / "insights.md")
        text = out.read_text(encoding="utf-8")
    assert "Headline here" in text
    assert "Title" in text
    assert "Narrative unavailable" not in text


# --- degraded fallback banner ---------------------------------------------------

def test_degraded_banner_renders_visibly_in_html_when_insights_is_none() -> None:
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    with tempfile.TemporaryDirectory() as tmp:
        out = render_eda_report_html(
            dataset_name="demo", stats=stats, figures=[], insights=None,
            out_path=Path(tmp) / "eda_report.html", degraded_reason="schema validation failed twice",
        )
        text = out.read_text(encoding="utf-8")
    assert "Narrative unavailable" in text
    assert "schema validation failed twice" in text
    # the deterministic stats must STILL be present even in degraded mode
    assert "monthly_charges.mean" in text


def test_degraded_banner_renders_visibly_in_markdown_when_insights_is_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = render_insights_markdown(
            dataset_name="demo", insights=None, out_path=Path(tmp) / "insights.md",
            degraded_reason="schema validation failed twice",
        )
        text = out.read_text(encoding="utf-8")
    assert "Narrative unavailable" in text
    assert "schema validation failed twice" in text


# --- no HTML injection from narrative text --------------------------------------

def test_narrative_text_is_html_escaped_in_the_report() -> None:
    """A malicious/careless narrative field containing raw HTML must never
    be injected unescaped into the rendered report."""
    df = _sample_df()
    stats = compute_eda_stats(df, target_column="churn")
    doc = InsightsDoc(
        headline="<script>alert('xss')</script>",
        insights=[
            Insight(title="t", observation="o", business_implication="b",
                    recommended_action="r", evidence_stat_key="churn.positive_rate")
        ],
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = render_eda_report_html(
            dataset_name="demo", stats=stats, figures=[], insights=doc, out_path=Path(tmp) / "eda_report.html"
        )
        text = out.read_text(encoding="utf-8")
    assert "<script>alert" not in text
    assert "&lt;script&gt;" in text


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
