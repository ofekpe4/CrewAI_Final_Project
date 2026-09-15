# telco_customer_churn — Insights

Insights on Customer Churn at Harbor & Vale


## Contract Length is Key to Retention

Customers with month-to-month contracts have a churn rate of 42.7%, compared to just 2.8% for those with two-year contracts.

**Business implication:** This stark difference indicates that contract length is a significant factor in customer retention. Retaining customers on longer contracts can reduce churn and stabilize revenue.

**Recommended action:** Implement targeted incentives to encourage month-to-month customers to switch to longer-term contracts, such as discounts or loyalty rewards.

*Evidence: `Contract.target_rate_by_category.Month-to-month`*


## Impact of Monthly Charges on Churn

There is a positive correlation of 0.193 between MonthlyCharges and churn, suggesting that higher monthly charges may contribute to increased churn rates.

**Business implication:** If customers perceive their monthly charges as too high, they may be more likely to leave, especially if they find cheaper alternatives.

**Recommended action:** Review pricing strategies and consider offering tiered pricing or discounts for long-term customers to enhance perceived value.

*Evidence: `MonthlyCharges.mean`*


## Gender and Churn Rates Are Similar

The churn rates for male (26.2%) and female (26.9%) customers are nearly identical, indicating that gender does not significantly influence churn.

**Business implication:** Marketing and retention strategies do not need to be gender-specific, allowing for a more streamlined approach to customer engagement.

**Recommended action:** Focus retention efforts on other demographic factors or service usage patterns rather than gender.

*Evidence: `gender.target_rate_by_category.Female`*


## Dependents Show Lower Churn Rates

Customers with dependents have a churn rate of 15.5%, compared to 31.3% for those without dependents.

**Business implication:** This suggests that customers with dependents may be more committed to their services, possibly due to family needs.

**Recommended action:** Develop targeted retention strategies for customers without dependents, who show higher churn rates.

*Evidence: `Dependents.target_rate_by_category.No`*


## Payment Method Influences Churn

Customers using Electronic Checks have a churn rate of 45.3%, significantly higher than those using other payment methods.

**Business implication:** This suggests that the payment method may correlate with customer satisfaction or financial stability.

**Recommended action:** Investigate the reasons behind the high churn rate among Electronic Check users and consider offering alternative payment options or incentives.

*Evidence: `PaymentMethod.target_rate_by_category.Electronic check`*


## Data caveats


- The dataset does not specify the currency for monetary values, making it unclear how to interpret financial metrics.

- These insights are based on observed associations and do not imply causation.

