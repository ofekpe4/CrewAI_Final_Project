# Model Card — telco_customer_churn

## Purpose

The purpose of this model is to predict customer churn for a telecommunications company, enabling proactive retention strategies.

## Intended use

This model is intended for use by customer retention teams to identify customers at risk of churning, allowing for targeted interventions.


## Out of scope


- Using the model for purposes outside of customer churn prediction, such as financial forecasting or market analysis.

- Applying the model to datasets that do not conform to the same structure or feature set.



## Training data summary

The training data consists of 7043 customer records with features including demographic information, service usage, and billing details. The target variable is binary, indicating whether a customer has churned.

## Metrics (machine-verified against `experiments.json`)

| Metric | Split | Variant | Value |
|---|---|---|---|
| roc_auc | test | Logistic Regression Baseline | 0.8495 |
| pr_auc | test | Logistic Regression Baseline | 0.6684 |
| f1 | test | Logistic Regression Baseline | 0.6195 |
| precision | test | Logistic Regression Baseline | 0.5068 |
| recall | test | Logistic Regression Baseline | 0.7968 |
| accuracy | test | Logistic Regression Baseline | 0.7402 |


## Limitations


- The model assumes that the dataset's 'customers' and 'churn this quarter' framing is treated as a single-snapshot cross-section, which may not capture temporal changes in customer behavior.

- The model assumes the measurement scale for monetary values remains constant, and any upstream changes in currency or scale would invalidate its predictions.

- Fairness and bias metrics were not measured, which limits the understanding of the model's performance across different demographic groups.


## Ethical considerations


- The model should be used responsibly to avoid discriminatory practices in customer retention efforts.

- Transparency in how the model's predictions are used is essential to maintain customer trust.


## Contract dependencies


- The dataset's 'customers' and 'churn this quarter' framing is treated as a single-snapshot cross-section (one row per customer, one observation point).


## Monitoring recommendations


- Regularly monitor the model's performance metrics to detect any drift in accuracy or other key performance indicators.

- Implement a feedback loop to capture the outcomes of retention strategies based on model predictions to refine future iterations.


---

*Winner selected deterministically by Python (`argmax` over cross-validated
primary metric). Every metric above is verified against
`artifacts/crew2/experiments.json` — no numeric claim in this document was
authored by an LLM without mechanical verification.*