# telco_customer_churn — Insights

Key Insights on Customer Churn at Harbor & Vale


## Contract Length is Critical for Retention

Customers with month-to-month contracts have a churn rate of 42.7%, compared to just 2.8% for two-year contracts (Contract.target_rate_by_category.Two year).

**Business implication:** This stark difference indicates that contract length is a significant factor in customer retention, suggesting that customers on shorter contracts are more likely to leave.

**Recommended action:** Implement incentives to encourage month-to-month customers to switch to longer-term contracts, such as discounts or loyalty rewards.

*Evidence: `Contract.target_rate_by_category.Month-to-month`*


## Higher Monthly Charges Correlate with Increased Churn

There is a positive correlation of 0.193 between MonthlyCharges and churn, indicating that as monthly charges increase, so does the likelihood of churn.

**Business implication:** This suggests that customers may perceive higher charges as less value, leading to dissatisfaction and increased churn.

**Recommended action:** Review pricing strategies and consider offering tiered pricing or value-added services to justify higher charges and improve customer satisfaction.

*Evidence: `MonthlyCharges.mean`*


## Dependents Correlate with Lower Churn Rates

Customers with dependents have a churn rate of 15.5%, compared to 31.3% for those without (Dependents.target_rate_by_category.No).

**Business implication:** This indicates that households with dependents may have different needs and expectations from their service providers.

**Recommended action:** Tailor services and marketing efforts to better meet the needs of families, potentially reducing churn in this segment.

*Evidence: `Dependents.target_rate_by_category.Yes`*


## Payment Method Influences Churn Rates

Customers using electronic checks have a churn rate of 45.3%, significantly higher than those using bank transfers (PaymentMethod.target_rate_by_category.Bank transfer (automatic)).

**Business implication:** This suggests that the payment method may affect customer satisfaction and retention.

**Recommended action:** Investigate the reasons behind higher churn among electronic check users and consider offering incentives for customers to switch to more stable payment methods.

*Evidence: `PaymentMethod.target_rate_by_category.Electronic check`*


## Gender Shows Minimal Impact on Churn Rates

Churn rates are 26.9% for females and 26.2% for males, indicating a negligible difference (gender.target_rate_by_category.Female and gender.target_rate_by_category.Male).

**Business implication:** This suggests that gender is not a significant factor in customer retention strategies.

**Recommended action:** Focus retention efforts on other more impactful factors rather than gender-based segmentation.

*Evidence: `gender.target_rate_by_category.Female`*


## Data caveats


- The dataset does not specify the currency for monetary columns, such as MonthlyCharges and TotalCharges.

- These insights are based on observed associations and do not imply causation.

