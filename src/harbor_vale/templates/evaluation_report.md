# Evaluation Report — {{ run_id }}

> Every number in this report is read directly from the machine-measured
> `experiments.json` produced by `ml/train.py` + `ml/evaluate.py`. No metric
> below was authored or estimated by an LLM.

## Experiment design

- **Primary metric:** `{{ experiments.primary_metric }}`
- **Metric rationale:** {{ plan.metric_rationale }}
- **Cross-validation:** `StratifiedKFold(n_splits={{ experiments.cv_folds }}, shuffle=True, random_state=42)`
- **Train/test split:** `train_test_split(test_size=0.2, stratify=y, random_state=42)`
- **Variants evaluated:** {{ experiments.variants | length }}

## Variant comparison (cross-validation, train split only)

| Variant | Estimator | {% for m in metric_order %}{{ m }} | {% endfor %}
|---|---|{% for m in metric_order %}---|{% endfor %}
{% for v in experiments.variants -%}
| {{ v.name }} | `{{ v.estimator }}` | {% for m in metric_order %}{{ "%.4f"|format(v.cv_metrics[m]) }} | {% endfor %}
{% endfor %}

### Variant rationale (agent judgment — narrative, no numbers)

{% for v in plan.variants %}
- **{{ v.name }}** (`{{ v.estimator }}`): {{ v.rationale }}
{% endfor %}

## Winner (selected by Python, `argmax({{ experiments.primary_metric }})` over CV metrics)

**`{{ experiments.winner.name }}`** (`{{ experiments.winner.estimator }}`)

### Winner — final held-out test-set evaluation

*The test set was touched exactly once, after model selection, for this evaluation only.*

| Metric | Value |
|---|---|
{% for m in metric_order -%}
| {{ m }} | {{ "%.4f"|format(experiments.winner.test_metrics[m]) }} |
{% endfor %}

**Confusion matrix** (`[[tn, fp], [fn, tp]]`): `{{ experiments.winner.test_metrics.confusion_matrix }}`

### Winner — cross-validation metrics (train split only, for reference)

| Metric | Value |
|---|---|
{% for m in metric_order -%}
| {{ m }} | {{ "%.4f"|format(experiments.winner.cv_metrics[m]) }} |
{% endfor %}

---

*Generated deterministically by `harbor_vale.tools.report_tools`. Source of truth: `artifacts/crew2/experiments.json`.*
