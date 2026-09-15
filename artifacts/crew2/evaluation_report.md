# Evaluation Report — 20260915T102608Z-b36bbce3

> Every number in this report is read directly from the machine-measured
> `experiments.json` produced by `ml/train.py` + `ml/evaluate.py`. No metric
> below was authored or estimated by an LLM.

## Experiment design

- **Primary metric:** `roc_auc`
- **Metric rationale:** Given the observed positive rate of approximately 26.5%, ROC-AUC is appropriate as it evaluates the model's ability to distinguish between churners and non-churners across all thresholds, which is crucial in this imbalanced classification problem.
- **Cross-validation:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`
- **Train/test split:** `train_test_split(test_size=0.2, stratify=y, random_state=42)`
- **Variants evaluated:** 2

## Variant comparison (cross-validation, train split only)

| Variant | Estimator | roc_auc | pr_auc | f1 | precision | recall | accuracy | 
|---|---|---|---|---|---|---|---|
| Logistic Regression Baseline | `logistic_regression` | 0.8502 | 0.6712 | 0.6334 | 0.5234 | 0.8020 | 0.7536 | 
| Random Forest Classifier | `random_forest` | 0.8436 | 0.6474 | 0.6243 | 0.5073 | 0.8114 | 0.7409 | 


### Variant rationale (agent judgment — narrative, no numbers)


- **Logistic Regression Baseline** (`logistic_regression`): Logistic regression provides a simple yet effective baseline model for binary classification, allowing us to assess the performance of more complex models against a straightforward approach.

- **Random Forest Classifier** (`random_forest`): The random forest model can capture complex interactions between features and is robust to overfitting, making it a strong candidate for improving classification performance in this imbalanced dataset.


## Winner (selected by Python, `argmax(roc_auc)` over CV metrics)

**`Logistic Regression Baseline`** (`logistic_regression`)

### Winner — final held-out test-set evaluation

*The test set was touched exactly once, after model selection, for this evaluation only.*

| Metric | Value |
|---|---|
| roc_auc | 0.8495 |
| pr_auc | 0.6684 |
| f1 | 0.6195 |
| precision | 0.5068 |
| recall | 0.7968 |
| accuracy | 0.7402 |


**Confusion matrix** (`[[tn, fp], [fn, tp]]`): `[[745, 290], [76, 298]]`

### Winner — cross-validation metrics (train split only, for reference)

| Metric | Value |
|---|---|
| roc_auc | 0.8502 |
| pr_auc | 0.6712 |
| f1 | 0.6334 |
| precision | 0.5234 |
| recall | 0.8020 |
| accuracy | 0.7536 |


---

*Generated deterministically by `harbor_vale.tools.report_tools`. Source of truth: `artifacts/crew2/experiments.json`.*