-- ============================================================
-- Join all order-level information
--
-- Base grain:
-- One row per order
--
-- All joins are LEFT JOINs so every order remains in the table.
-- ============================================================

CREATE OR REPLACE TABLE joined_orders AS
SELECT
    -- --------------------------------------------------------
    -- Order identifiers and lifecycle information
    -- --------------------------------------------------------
    o.order_id,
    o.customer_id,
    o.order_status,

    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,

    -- --------------------------------------------------------
    -- Customer information
    -- --------------------------------------------------------
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,

    -- --------------------------------------------------------
    -- Order-item features
    -- --------------------------------------------------------
    i.item_count,
    i.unique_product_count,
    i.unique_seller_count,
    i.unique_seller_state_count,
    i.unique_category_count,

    i.total_item_price,
    i.average_item_price,
    i.minimum_item_price,
    i.maximum_item_price,

    i.total_freight,
    i.average_freight_per_item,
    i.maximum_freight_per_item,
    i.freight_to_price_ratio,

    i.total_product_weight_g,
    i.average_product_weight_g,
    i.maximum_product_weight_g,

    i.total_product_volume_cm3,
    i.average_product_volume_cm3,
    i.maximum_product_volume_cm3,

    i.average_product_photos,
    i.maximum_product_photos,

    i.missing_weight_item_count,
    i.missing_volume_item_count,
    i.missing_category_item_count,

    i.primary_seller_state,
    i.earliest_shipping_limit_date,
    i.latest_shipping_limit_date,

    -- --------------------------------------------------------
    -- Payment features
    -- --------------------------------------------------------
    p.payment_count,
    p.payment_type_count,

    p.total_payment_value,
    p.average_payment_value,
    p.minimum_payment_value,
    p.maximum_payment_value,

    p.maximum_installments,
    p.average_installments,

    p.primary_payment_type,
    p.primary_payment_value,

    p.used_credit_card,
    p.used_voucher,
    p.used_boleto,
    p.used_debit_card,

    -- --------------------------------------------------------
    -- Derived order-level features
    -- --------------------------------------------------------

    CASE
        WHEN c.customer_state IS NULL
          OR i.primary_seller_state IS NULL
        THEN NULL

        WHEN c.customer_state = i.primary_seller_state
        THEN 1

        ELSE 0
    END AS same_state_delivery,

    CASE
        WHEN i.order_id IS NOT NULL THEN 1
        ELSE 0
    END AS has_item_features,

    CASE
        WHEN p.order_id IS NOT NULL THEN 1
        ELSE 0
    END AS has_payment_features,

    p.total_payment_value
        - (
            i.total_item_price
            + i.total_freight
        ) AS payment_order_value_difference

FROM orders AS o

LEFT JOIN customers AS c
    ON o.customer_id = c.customer_id

LEFT JOIN order_item_features AS i
    ON o.order_id = i.order_id

LEFT JOIN payment_features AS p
    ON o.order_id = p.order_id;