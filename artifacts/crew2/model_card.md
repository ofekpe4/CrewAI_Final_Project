# Model Card — telco_customer_churn

## Purpose

The purpose of this model is to predict customer churn for a telecommunications company, enabling proactive retention strategies.

## Intended use

This model is intended for use by customer retention teams to identify customers at risk of churning, allowing for targeted interventions.


## Out of scope


- Using the model for purposes outside of customer churn prediction, such as financial forecasting.

- Applying the model to datasets not aligned with the training data characteristics.



## Training data summary

The training data consists of 7043 customer records with 21 features, including demographic information and service usage metrics. The target variable is binary, indicating whether a customer has churned.

## Metrics (machine-verified against `experiments.json`)

| Metric | Split | Variant | Value |
|---|---|---|---|
| roc_auc | test | Logistic Regression Base | 0.8478 |
| pr_auc | test | Logistic Regression Base | 0.6658 |
| f1 | test | Logistic Regression Base | 0.6176 |
| precision | test | Logistic Regression Base | 0.5042 |
| recall | test | Logistic Regression Base | 0.7968 |
| accuracy | test | Logistic Regression Base | 0.7381 |


## Limitations


- The model assumes the measurement scale for monetary columns remains constant; any upstream changes in currency or scale would invalidate predictions.

- Fairness and bias metrics were not measured; therefore, the model's performance across different demographic groups is unknown.


## Ethical considerations


- The model should be used responsibly to avoid discriminatory practices in customer retention efforts.

- Transparency with customers regarding the use of their data for predictive modeling is essential.


## Contract dependencies


- The dataset's 'customers' and 'churn this quarter' framing is treated as a single-snapshot cross-section (one row per customer, one observation point).


## Monitoring recommendations


- Regularly monitor model performance metrics to detect any drift in accuracy or other key performance indicators.

- Implement a feedback loop to update the model with new data and retrain as necessary to maintain performance.


---

*Winner selected deterministically by Python (`argmax` over cross-validated
primary metric). Every metric above is verified against
`artifacts/crew2/experiments.json` — no numeric claim in this document was
authored by an LLM without mechanical verification.*