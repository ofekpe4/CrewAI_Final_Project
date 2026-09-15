# telco_customer_churn — Insights

Insights on Customer Churn at Harbor & Vale


## Contract Length is Key to Retention

Customers with month-to-month contracts have a churn rate of 42.7%, compared to only 2.8% for those with two-year contracts.

**Business implication:** This stark difference indicates that contract length is a significant factor in customer retention, suggesting that month-to-month customers are at a higher risk of leaving.

**Recommended action:** Implement targeted incentives to encourage month-to-month customers to switch to longer-term contracts, such as discounts or loyalty rewards.

*Evidence: `Contract.target_rate_by_category.Month-to-month`*


## Impact of Monthly Charges on Churn

There is a positive correlation (0.193) between Monthly Charges and churn, indicating that higher monthly fees may contribute to customer dissatisfaction.

**Business implication:** If customers perceive their monthly charges as too high, they may be more likely to churn, especially if they feel they are not receiving adequate value.

**Recommended action:** Review pricing strategies and consider offering tiered pricing or value-added services to enhance perceived value for customers with higher monthly charges.

*Evidence: `MonthlyCharges.mean`*


## Dependents Reduce Churn Risk

Customers with dependents have a churn rate of 15.5%, significantly lower than the 31.3% rate for those without dependents.

**Business implication:** This indicates that families or customers with dependents may have different needs or loyalty factors that keep them engaged with the service.

**Recommended action:** Create family-oriented plans or packages that cater specifically to customers with dependents to enhance retention.

*Evidence: `Dependents.target_rate_by_category.Yes`*


## Payment Method Influences Churn

Customers using electronic checks have a churn rate of 45.3%, the highest among payment methods.

**Business implication:** This suggests that the payment method may correlate with customer satisfaction or ease of use, impacting their likelihood to stay.

**Recommended action:** Investigate the payment process for electronic check users and consider offering incentives for switching to more stable payment methods.

*Evidence: `PaymentMethod.target_rate_by_category.Electronic check`*


## Gender Differences in Churn Rates

Female customers have a churn rate of 26.9%, while male customers have a churn rate of 26.2%.

**Business implication:** This slight difference suggests that gender may play a role in customer retention strategies, indicating a need for tailored approaches.

**Recommended action:** Analyze customer feedback by gender to identify specific concerns or preferences that could inform targeted retention strategies.

*Evidence: `gender.target_rate_by_category.Female`*


## Data caveats


- The dataset does not specify the currency for monetary columns.

- These insights are based on observed associations and do not imply causation.

