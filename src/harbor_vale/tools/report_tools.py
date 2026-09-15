"""Deterministic rendering of Crew 2's two report artifacts (PROJECT_PLAN.md
§G.2/§G.3, Phase 7 "Evaluation report architecture" / "ModelCard renderer").

**Metric truth hierarchy (Phase 7 acceptance):** `ExperimentPlan` is agent
intent; `ml/train.py`+`ml/evaluate.py` are execution; `experiments.json` is
measured truth; this module renders VIEWS of that measured truth — it never
computes, invents, or rounds a number itself. `render_evaluation_report_markdown`
takes the already-built `experiments`-shaped dict (`ml.evaluate.
build_experiments_artifact`'s output) and a validated `ExperimentPlan` for
narrative context (rationale text only); `render_model_card_markdown` takes
an already-guardrail-validated `ModelCard` (every `MetricClaim` in it
already mechanically verified against the same `experiments` dict) or, in
degraded mode, builds its own minimal truthful fallback directly from
`experiments`/`contract.assumptions` — never from unvalidated LLM text.

Same Jinja2 file-template pattern as `tools/eda_tools.py`'s
`render_eda_report_html`/`render_insights_markdown` — reused here for
consistency, not reinvented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from harbor_vale.io_paths import PROJECT_ROOT
from harbor_vale.plans.experiment_plan import ExperimentPlan
from harbor_vale.plans.model_card import ModelCard

_TEMPLATES_DIR = PROJECT_ROOT / "src" / "harbor_vale" / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "htm"), default_for_string=False),
)

_METRIC_ORDER = ("roc_auc", "pr_auc", "f1", "precision", "recall", "accuracy")


def render_evaluation_report_markdown(
    *,
    run_id: str,
    plan: ExperimentPlan,
    experiments: dict[str, Any],
    out_path: Path | str,
) -> Path:
    """Render `evaluation_report.md`. Every metric value, every confusion
    matrix, and the winner name are read directly from `experiments`
    (Python/sklearn measured truth) — `plan` supplies only narrative
    context (`metric_rationale`, each variant's `rationale`), never a
    number."""
    template = _jinja_env.get_template("evaluation_report.md")
    markdown = template.render(
        run_id=run_id,
        plan=plan,
        experiments=experiments,
        metric_order=_METRIC_ORDER,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return out_path


def render_model_card_markdown(
    *,
    card: ModelCard | None,
    degraded: bool,
    degraded_reason: str | None,
    experiments: dict[str, Any],
    contract_assumptions: list[str],
    dataset_name: str,
    out_path: Path | str,
) -> Path:
    """Render `model_card.md`.

    Normal mode (`degraded=False`): renders ONLY the validated `card`'s
    fields — no raw HTML/Markdown injection surface, since every field is a
    plain string/list already typed and length-checked by `ModelCard`'s own
    Pydantic validators (`plans/model_card.py`); Jinja2's default
    (non-autoescaped, `.md` extension) rendering is safe here because the
    content is plain narrative text, not attacker-controlled markup destined
    for a browser.

    Degraded mode (`degraded=True`): `card` is ignored entirely (it is
    `None` per `guardrails.guardrail_model_card`'s contract) — this function
    builds its own minimal, truthful fallback directly from `experiments`
    (the winner's real test metrics) and `contract_assumptions` (the
    contract's own real `assumptions` list), with the required visible
    banner. No LLM-authored text of any kind appears in degraded mode.
    """
    template = _jinja_env.get_template("model_card.md")
    winner = experiments["winner"]
    markdown = template.render(
        card=card,
        degraded=degraded,
        degraded_reason=degraded_reason,
        dataset_name=dataset_name,
        winner=winner,
        contract_assumptions=contract_assumptions,
        metric_order=_METRIC_ORDER,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    return out_path
