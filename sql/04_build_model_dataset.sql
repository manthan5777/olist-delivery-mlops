-- ============================================================
-- Build the master machine-learning dataset
--
-- Grain:
-- One row represents one delivered order.
--
-- Prediction moment:
-- Immediately after payment approval.
--
-- Targets:
-- 1. late_delivery          -> classification
-- 2. actual_delivery_days   -> regression
-- ============================================================

CREATE OR REPLACE TABLE model_dataset AS
SELECT
    -- --------------------------------------------------------
    -- Tracking fields
    -- These help us identify records and perform a time split.
    -- They will not be model input features.
    -- --------------------------------------------------------
    order_id,
    customer_id,
    customer_unique_id,
    order_purchase_timestamp,
    order_approved_at,

    -- --------------------------------------------------------
    -- Customer and seller location features
    -- --------------------------------------------------------
    customer_state,
    primary_seller_state,
    same_state_delivery,

    -- --------------------------------------------------------
    -- Purchase-time features
    -- --------------------------------------------------------
    EXTRACT(YEAR FROM order_purchase_timestamp)
        AS purchase_year,

    EXTRACT(MONTH FROM order_purchase_timestamp)
        AS purchase_month,

    EXTRACT(DAYOFWEEK FROM order_purchase_timestamp)
        AS purchase_weekday,

    EXTRACT(HOUR FROM order_purchase_timestamp)
        AS purchase_hour,

    -- Time between order placement and payment approval.
    -- Since our prediction happens after payment approval,
    -- this is available at prediction time.
    DATE_DIFF(
        'second',
        order_purchase_timestamp,
        order_approved_at
    ) / 3600.0 AS approval_delay_hours,

    -- Number of days originally promised to the customer.
    -- Estimated delivery is known when the order is placed.
    DATE_DIFF(
        'second',
        order_purchase_timestamp,
        order_estimated_delivery_date
    ) / 86400.0 AS promised_delivery_days,

    -- Seller's available shipping window.
    DATE_DIFF(
        'second',
        order_purchase_timestamp,
        latest_shipping_limit_date
    ) / 86400.0 AS seller_shipping_window_days,

    -- --------------------------------------------------------
    -- Item features
    -- --------------------------------------------------------
    item_count,
    unique_product_count,
    unique_seller_count,
    unique_seller_state_count,
    unique_category_count,

    total_item_price,
    average_item_price,
    minimum_item_price,
    maximum_item_price,

    total_freight,
    average_freight_per_item,
    maximum_freight_per_item,
    freight_to_price_ratio,

    total_product_weight_g,
    average_product_weight_g,
    maximum_product_weight_g,

    total_product_volume_cm3,
    average_product_volume_cm3,
    maximum_product_volume_cm3,

    average_product_photos,
    maximum_product_photos,

    missing_weight_item_count,
    missing_volume_item_count,
    missing_category_item_count,

    -- --------------------------------------------------------
    -- Payment features
    -- --------------------------------------------------------
    payment_count,
    payment_type_count,

    total_payment_value,
    average_payment_value,
    minimum_payment_value,
    maximum_payment_value,

    maximum_installments,
    average_installments,

    primary_payment_type,

    used_credit_card,
    used_voucher,
    used_boleto,
    used_debit_card,

    -- --------------------------------------------------------
    -- Regression target
    -- Actual end-to-end delivery duration
    -- --------------------------------------------------------
    DATE_DIFF(
        'second',
        order_purchase_timestamp,
        order_delivered_customer_date
    ) / 86400.0 AS actual_delivery_days,

    -- --------------------------------------------------------
    -- Classification target
    -- 1 means delivered after the promised date
    -- 0 means delivered on or before the promised date
    -- --------------------------------------------------------
    CASE
        WHEN order_delivered_customer_date
             > order_estimated_delivery_date
        THEN 1
        ELSE 0
    END AS late_delivery,

    -- Useful for analysis, but not a model input.
    DATE_DIFF(
        'second',
        order_estimated_delivery_date,
        order_delivered_customer_date
    ) / 86400.0 AS lateness_days

FROM joined_orders

WHERE order_status = 'delivered'

  -- Required for the regression target
  AND order_purchase_timestamp IS NOT NULL
  AND order_delivered_customer_date IS NOT NULL

  -- Required for the classification target
  AND order_estimated_delivery_date IS NOT NULL

  -- Prediction happens after approval
  AND order_approved_at IS NOT NULL

  -- Require complete item and payment summaries
  AND has_item_features = 1
  AND has_payment_features = 1;