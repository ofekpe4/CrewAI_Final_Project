# Model Card — {{ dataset_name }}

{% if degraded -%}
> ⚠️ **Narrative sections auto-generated after agent output failed validation.**
{% if degraded_reason %}> Reason: {{ degraded_reason }}
{% endif %}

## Purpose

Predict customer churn (`{{ winner.name }}`, `{{ winner.estimator }}`) for the
Telco Customer Churn dataset, selected deterministically by Python on the
declared primary metric.

## Metrics (machine-measured, held-out test set)

| Metric | Value |
|---|---|
{% for m in metric_order -%}
| {{ m }} | {{ "%.4f"|format(winner.test_metrics[m]) }} |
{% endfor %}

## Contract dependencies

{% for a in contract_assumptions %}
- {{ a }}
{% endfor %}

## Limitations

- This model card's narrative sections (intended use, ethical considerations,
  monitoring recommendations) could not be generated this run — only the
  machine-measured metrics and real contract assumptions above are shown.
- No fairness/bias metric was measured for this model; none is claimed here.

{%- else -%}

## Purpose

{{ card.purpose }}

## Intended use

{{ card.intended_use }}

{% if card.out_of_scope_use %}
## Out of scope

{% for u in card.out_of_scope_use %}
- {{ u }}
{% endfor %}
{% endif %}

## Training data summary

{{ card.training_data_summary }}

## Metrics (machine-verified against `experiments.json`)

| Metric | Split | Variant | Value |
|---|---|---|---|
{% for claim in card.metrics_summary -%}
| {{ claim.metric }} | {{ claim.split }} | {{ claim.variant_name }} | {{ "%.4f"|format(claim.value) }} |
{% endfor %}

## Limitations

{% for l in card.limitations %}
- {{ l }}
{% endfor %}

## Ethical considerations

{% for e in card.ethical_considerations %}
- {{ e }}
{% endfor %}

## Contract dependencies

{% for d in card.contract_dependencies %}
- {{ d }}
{% endfor %}

## Monitoring recommendations

{% for m in card.monitoring_recommendations %}
- {{ m }}
{% endfor %}

{%- endif %}

---

*Winner selected deterministically by Python (`argmax` over cross-validated
primary metric). Every metric above is verified against
`artifacts/crew2/experiments.json` — no numeric claim in this document was
authored by an LLM without mechanical verification.*
