# Training Data EDA Summary

## Scope

- Training rows inspected: 67,518.
- Validation data was used only for feature-distribution drift; no validation target was read.
- Test data was not loaded or inspected.
- Outliers are reported, not removed.

## Target Distribution

- Late-delivery rate: 9.03% (6,095 late orders).
- Actual delivery days: mean 13.82, median 11.47, p95 32.00, maximum 209.63.

## Highest Missingness

- `average_product_photos`: 1,196 (1.77%)
- `maximum_product_photos`: 1,196 (1.77%)
- `average_product_volume_cm3`: 16 (0.02%)
- `average_product_weight_g`: 16 (0.02%)
- `maximum_product_volume_cm3`: 16 (0.02%)
- `maximum_product_weight_g`: 16 (0.02%)
- `total_product_volume_cm3`: 16 (0.02%)
- `total_product_weight_g`: 16 (0.02%)

## Strongest Train-to-Validation Feature Drift

- `purchase_month` (categorical): drift score 0.8194, validation unseen rate 0.00%
- `purchase_year` (categorical): drift score 0.6469, validation unseen rate 0.00%
- `approval_delay_hours` (numeric): drift score 0.4673, validation unseen rate 0.00%
- `total_freight` (numeric): drift score 0.2657, validation unseen rate 0.00%
- `maximum_freight_per_item` (numeric): drift score 0.2383, validation unseen rate 0.00%
- `average_freight_per_item` (numeric): drift score 0.2234, validation unseen rate 0.00%
- `seller_shipping_window_days` (numeric): drift score 0.1920, validation unseen rate 0.00%
- `promised_delivery_days` (numeric): drift score 0.1104, validation unseen rate 0.00%
- `purchase_weekday` (categorical): drift score 0.0514, validation unseen rate 0.00%
- `customer_state` (categorical): drift score 0.0506, validation unseen rate 0.00%

## Extreme Values

- `used_credit_card`: 15,693 IQR-rule outliers; skewness -1.27
- `used_boleto`: 13,887 IQR-rule outliers; skewness 1.46
- `maximum_product_weight_g`: 9,814 IQR-rule outliers; skewness 3.55
- `average_product_weight_g`: 9,768 IQR-rule outliers; skewness 3.58
- `total_product_weight_g`: 9,509 IQR-rule outliers; skewness 6.64
- `approval_delay_hours`: 7,183 IQR-rule outliers; skewness 5.09
- `average_freight_per_item`: 7,102 IQR-rule outliers; skewness 5.55
- `maximum_freight_per_item`: 7,055 IQR-rule outliers; skewness 5.46
- `item_count`: 6,756 IQR-rule outliers; skewness 8.11
- `total_freight`: 6,629 IQR-rule outliers; skewness 8.58

## Suspicious or Impossible Values

- No numeric input feature has a negative value; verify domain-specific bounds before modelling.

## Redundancy

- 26 potential redundant feature relationships are listed in `redundant_columns.csv`.

## Next-Step Guardrails

- Fit all learned transformations and route frequencies on training data only.
- Preserve the 47-feature API contract; generate derived features internally.
- Do not select features, tune models, or tune thresholds from test data.
