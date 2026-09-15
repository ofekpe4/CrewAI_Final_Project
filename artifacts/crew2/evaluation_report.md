# Evaluation Report — 20260915T123249Z-61d6335c

> Every number in this report is read directly from the machine-measured
> `experiments.json` produced by `ml/train.py` + `ml/evaluate.py`. No metric
> below was authored or estimated by an LLM.

## Experiment design

- **Primary metric:** `roc_auc`
- **Metric rationale:** Given the observed positive rate of approximately 26.5%, ROC-AUC is appropriate as it evaluates the model's ability to distinguish between churners and non-churners across all thresholds, which is crucial in this imbalanced classification scenario.
- **Cross-validation:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`
- **Train/test split:** `train_test_split(test_size=0.2, stratify=y, random_state=42)`
- **Variants evaluated:** 2

## Variant comparison (cross-validation, train split only)

| Variant | Estimator | roc_auc | pr_auc | f1 | precision | recall | accuracy | 
|---|---|---|---|---|---|---|---|
| Logistic Regression Base | `logistic_regression` | 0.8493 | 0.6697 | 0.6341 | 0.5240 | 0.8027 | 0.7542 | 
| Random Forest Classifier | `random_forest` | 0.8440 | 0.6513 | 0.5325 | 0.6901 | 0.4334 | 0.7980 | 


### Variant rationale (agent judgment — narrative, no numbers)


- **Logistic Regression Base** (`logistic_regression`): Logistic regression provides a straightforward probabilistic interpretation and is effective for binary classification tasks, making it a solid baseline model.

- **Random Forest Classifier** (`random_forest`): Random forests can capture complex interactions between features and are robust to overfitting, making them a strong candidate for improving classification performance in this dataset.


## Winner (selected by Python, `argmax(roc_auc)` over CV metrics)

**`Logistic Regression Base`** (`logistic_regression`)

### Winner — final held-out test-set evaluation

*The test set was touched exactly once, after model selection, for this evaluation only.*

| Metric | Value |
|---|---|
| roc_auc | 0.8478 |
| pr_auc | 0.6658 |
| f1 | 0.6176 |
| precision | 0.5042 |
| recall | 0.7968 |
| accuracy | 0.7381 |


**Confusion matrix** (`[[tn, fp], [fn, tp]]`): `[[742, 293], [76, 298]]`

### Winner — cross-validation metrics (train split only, for reference)

| Metric | Value |
|---|---|
| roc_auc | 0.8493 |
| pr_auc | 0.6697 |
| f1 | 0.6341 |
| precision | 0.5240 |
| recall | 0.8027 |
| accuracy | 0.7542 |


---

*Generated deterministically by `harbor_vale.tools.report_tools`. Source of truth: `artifacts/crew2/experiments.json`.*