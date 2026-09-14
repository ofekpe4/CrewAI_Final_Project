"""Deterministic EDA statistics, figures, and rendering (PROJECT_PLAN.md §D.2,
§I: "סטטיסטיקות EDA, גרפים ... ✅ Python ... pandas · matplotlib").

Everything in this module is measurement or rendering, never interpretation.
`compute_eda_stats()` returns a **flat** `dict[str, Any]` — the single
source of truth `plans/insights_doc.py`'s `evidence_stat_key` anti-
hallucination check validates every insight against (§D.2 point 7). The
future EDA & Insights Analyst agent may explain what a number *means*; it
may never produce a number that isn't already a key in this dictionary.

`matplotlib` is used with the non-interactive `Agg` backend (no GUI
dependency, safe in a test/CI/server process) and every figure is closed
after saving, so repeated calls never leak figure objects.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — must precede pyplot import; no GUI dependency
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from harbor_vale.io_paths import PROJECT_ROOT  # noqa: E402
from harbor_vale.plans.insights_doc import InsightsDoc  # noqa: E402

_TEMPLATES_DIR = PROJECT_ROOT / "src" / "harbor_vale" / "templates"

_MAX_CATEGORY_LEVELS_FOR_TARGET_RATE = 20
"""A categorical column's per-category target rate is only computed up to
this many distinct levels — beyond that, a bar chart of target rate by
category stops being a legible EDA artifact."""


def _stat_key(*parts: str) -> str:
    """A stable, deterministic key-naming scheme:
    `"<column>.<stat_name>"` or `"<column>.<stat_name>.<category>"`. Never
    includes a timestamp, random id, or anything non-reproducible."""
    return ".".join(parts)


def compute_eda_stats(
    df: "pd.DataFrame", *, target_column: str | None = None
) -> dict[str, Any]:
    """Deterministic EDA statistics as a **flat** dict, keyed by stable
    `"<column>.<stat>"`-style strings (see `_stat_key`).

    Includes, per numeric column: `count`, `mean`, `median`, `std`, `min`,
    `max`. Per categorical column: `unique_count`, and — if `target_column`
    is given and the column has a modest cardinality — the target's
    positive rate broken down by category (§D.2 point 4: "target rate לפי
    חתך"). If `target_column` is itself binary/numeric, also records its
    overall `positive_rate`. Also records dataset-level `row_count`,
    `column_count`.
    """
    stats: dict[str, Any] = {
        "dataset.row_count": int(len(df)),
        "dataset.column_count": int(len(df.columns)),
    }

    target_is_binary_numeric = False
    if target_column is not None and target_column in df.columns:
        target_series = df[target_column]
        if pd.api.types.is_numeric_dtype(target_series):
            unique_vals = set(target_series.dropna().unique().tolist())
            if unique_vals <= {0, 1}:
                target_is_binary_numeric = True
                stats[_stat_key(target_column, "positive_rate")] = float(target_series.mean())
                stats[_stat_key(target_column, "positive_count")] = int(target_series.sum())
                stats[_stat_key(target_column, "negative_count")] = int(
                    len(target_series) - target_series.sum()
                )

    for column in df.columns:
        series = df[column]
        if column == target_column:
            continue
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            non_null = series.dropna()
            if non_null.empty:
                continue
            stats[_stat_key(column, "count")] = int(non_null.count())
            stats[_stat_key(column, "mean")] = float(non_null.mean())
            stats[_stat_key(column, "median")] = float(non_null.median())
            stats[_stat_key(column, "std")] = float(non_null.std()) if len(non_null) > 1 else 0.0
            stats[_stat_key(column, "min")] = float(non_null.min())
            stats[_stat_key(column, "max")] = float(non_null.max())
        else:
            unique_count = int(series.nunique(dropna=True))
            stats[_stat_key(column, "unique_count")] = unique_count
            if (
                target_is_binary_numeric
                and 0 < unique_count <= _MAX_CATEGORY_LEVELS_FOR_TARGET_RATE
            ):
                grouped = df.groupby(column, dropna=True)[target_column].mean()
                for category, rate in grouped.items():
                    stats[_stat_key(column, "target_rate_by_category", str(category))] = float(rate)

    return stats


def compute_numeric_correlations(
    df: "pd.DataFrame", *, columns: list[str] | None = None
) -> dict[str, float]:
    """Pairwise Pearson correlation between numeric columns, as a flat
    `dict[str, float]` keyed `"<col_a>__vs__<col_b>"` (alphabetically
    ordered pair, so the same pair never appears twice under two different
    keys). Only pairs with a defined (non-NaN) correlation are included —
    §D.2 point 4: "קורלציות ... רק כשתקף" (only where valid)."""
    numeric_df = df.select_dtypes(include="number")
    if columns is not None:
        numeric_df = numeric_df[[c for c in columns if c in numeric_df.columns]]
    corr = numeric_df.corr(numeric_only=True)
    result: dict[str, float] = {}
    cols = sorted(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            value = corr.loc[a, b]
            if pd.notna(value):
                result[f"{a}__vs__{b}"] = float(value)
    return result


# ---------------------------------------------------------------------------
# Figures — deterministic, closed, reproducibly named.
# ---------------------------------------------------------------------------


def _deterministic_figure_name(kind: str, column: str) -> str:
    """A stable filename derived only from `kind`/`column` — no timestamp,
    no random suffix, so re-running the same EDA on the same data produces
    byte-identical filenames every time."""
    safe_column = "".join(c if c.isalnum() else "_" for c in column)
    return f"{kind}__{safe_column}.png"


def generate_target_rate_figure(
    df: "pd.DataFrame", *, column: str, target_column: str, out_dir: Path | str
) -> Path:
    """A bar chart of `target_column`'s positive rate, grouped by `column`.
    Deterministic given the same data (matplotlib's default rendering is
    itself deterministic for a static bar chart with no random layout).
    The figure is closed immediately after saving.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grouped = df.groupby(column, dropna=True)[target_column].mean().sort_index()

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(grouped.index.astype(str), grouped.values, color="#2b6cb0")
    ax.set_xlabel(column)
    ax.set_ylabel(f"{target_column} rate")
    ax.set_title(f"{target_column} rate by {column}")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()

    out_path = out_dir / _deterministic_figure_name("target_rate_by", column)
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path


def generate_numeric_distribution_figure(
    df: "pd.DataFrame", *, column: str, out_dir: Path | str, bins: int = 30
) -> Path:
    """A histogram of one numeric column. Deterministic given the same
    data and `bins` value."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    series = df[column].dropna()

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(series.values, bins=bins, color="#2f855a", edgecolor="white")
    ax.set_xlabel(column)
    ax.set_ylabel("count")
    ax.set_title(f"Distribution of {column}")
    fig.tight_layout()

    out_path = out_dir / _deterministic_figure_name("distribution", column)
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return out_path


def sha256_of_file(path: Path | str) -> str:
    """Hash a generated figure's actual bytes — used by tests to prove
    "same input data -> byte-identical figure" without eyeballing images."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Jinja2 rendering — `eda_report.html` and `insights.md` (§D.2 point 8).
#
# Deterministic rendering ONLY: the template receives a VALIDATED
# `InsightsDoc` (or none at all, in which case the degraded banner renders
# instead — §D.2 point 9's fallback design). No Agent fallback orchestration
# lives here (that is Phase 6's job); this module only implements the
# deterministic renderer/fallback capability Phase 6 will call.
#
# The HTML template is loaded with Jinja2's `select_autoescape` — every
# narrative field (headline, observation, business_implication,
# recommended_action, data_caveats) is HTML-escaped automatically, so
# arbitrary text a future LLM produces can never inject raw HTML/script
# into the rendered report (§Phase 5 explicit instruction: "Do not allow
# arbitrary HTML generation from future LLM text").
# ---------------------------------------------------------------------------

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "htm"), default_for_string=False),
)


def render_eda_report_html(
    *,
    dataset_name: str,
    stats: dict[str, Any],
    figures: list[str],
    insights: InsightsDoc | None,
    out_path: Path | str,
    degraded_reason: str | None = None,
) -> Path:
    """Render `eda_report.html`.

    Args:
        figures: figure paths/filenames to embed, already relative to
            `out_path`'s own directory (this function does not compute that
            relationship — callers pass exactly what should appear in an
            `<img src="...">`).
        insights: a VALIDATED `InsightsDoc`, or `None` — if `None`, the
            degraded banner renders instead (§D.2 point 9): the report
            still exists, with every deterministic stat/figure, and clearly
            shows the narrative is unavailable. This function never
            constructs a fallback `InsightsDoc` itself; that is the
            caller's decision to make (or not make).
    """
    template = _jinja_env.get_template("eda_report.html")
    html = template.render(
        dataset_name=dataset_name,
        stats=stats,
        figures=figures,
        insights=insights,
        degraded=insights is None,
        degraded_reason=degraded_reason,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_insights_markdown(
    *,
    dataset_name: str,
    insights: InsightsDoc | None,
    out_path: Path | str,
    degraded_reason: str | None = None,
) -> Path:
    """Render `insights.md`. Same degraded-banner fallback contract as
    `render_eda_report_html` — `insights=None` renders a clearly visible
    degraded banner instead of narrative content, never a silently empty
    or fabricated file."""
    template = _jinja_env.get_template("insights.md")
    markdown = template.render(
        dataset_name=dataset_name,
        insights=insights,
        degraded=insights is None,
        degraded_reason=degraded_reason,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return out_path
