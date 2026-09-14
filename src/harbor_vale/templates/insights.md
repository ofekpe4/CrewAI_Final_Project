# {{ dataset_name }} — Insights

{% if degraded -%}
> ⚠️ **Narrative unavailable — the analyst agent's output failed schema validation after 2 retries.**
{% if degraded_reason %}> Reason: {{ degraded_reason }}
{% endif %}
{%- else -%}
{{ insights.headline }}

{% for insight in insights.insights %}
## {{ insight.title }}

{{ insight.observation }}

**Business implication:** {{ insight.business_implication }}

**Recommended action:** {{ insight.recommended_action }}

*Evidence: `{{ insight.evidence_stat_key }}`*

{% endfor -%}
{% if insights.data_caveats %}
## Data caveats

{% for caveat in insights.data_caveats %}
- {{ caveat }}
{% endfor %}
{% endif -%}
{%- endif %}
