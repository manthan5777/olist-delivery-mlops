-- ============================================================
-- STEP 1: Enrich every order item with product and seller data
-- Grain: one row per order item
-- ============================================================

CREATE OR REPLACE TABLE enriched_order_items AS
SELECT
    -- Original order-item identifiers
    oi.order_id,
    oi.order_item_id,
    oi.product_id,
    oi.seller_id,

    -- Commercial information
    oi.price,
    oi.freight_value,
    oi.shipping_limit_date,

    -- Product information
    p.product_category_name,
    p.product_name_lenght,
    p.product_description_lenght,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,

    -- Product volume derived from dimensions
    (
        p.product_length_cm
        * p.product_height_cm
        * p.product_width_cm
    ) AS product_volume_cm3,

    -- Seller information
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state

FROM order_items AS oi

LEFT JOIN products AS p
    ON oi.product_id = p.product_id

LEFT JOIN sellers AS s
    ON oi.seller_id = s.seller_id;


-- ============================================================
-- STEP 2: Convert many item rows into one row per order
-- Grain: one row per order
-- ============================================================

CREATE OR REPLACE TABLE order_item_features AS
SELECT
    order_id,

    -- Number of items and entities
    COUNT(*) AS item_count,
    COUNT(DISTINCT product_id) AS unique_product_count,
    COUNT(DISTINCT seller_id) AS unique_seller_count,
    COUNT(DISTINCT seller_state) AS unique_seller_state_count,
    COUNT(DISTINCT product_category_name)
        AS unique_category_count,

    -- Price features
    SUM(price) AS total_item_price,
    AVG(price) AS average_item_price,
    MIN(price) AS minimum_item_price,
    MAX(price) AS maximum_item_price,

    -- Freight features
    SUM(freight_value) AS total_freight,
    AVG(freight_value) AS average_freight_per_item,
    MAX(freight_value) AS maximum_freight_per_item,

    -- Freight compared with product value
    CASE
        WHEN SUM(price) > 0
        THEN SUM(freight_value) / SUM(price)
        ELSE NULL
    END AS freight_to_price_ratio,

    -- Product-weight features
    SUM(product_weight_g) AS total_product_weight_g,
    AVG(product_weight_g) AS average_product_weight_g,
    MAX(product_weight_g) AS maximum_product_weight_g,

    -- Product-volume features
    SUM(product_volume_cm3) AS total_product_volume_cm3,
    AVG(product_volume_cm3) AS average_product_volume_cm3,
    MAX(product_volume_cm3) AS maximum_product_volume_cm3,

    -- Listing-quality features
    AVG(product_photos_qty) AS average_product_photos,
    MAX(product_photos_qty) AS maximum_product_photos,

    -- Missing-information indicators
    SUM(
        CASE
            WHEN product_weight_g IS NULL THEN 1
            ELSE 0
        END
    ) AS missing_weight_item_count,

    SUM(
        CASE
            WHEN product_volume_cm3 IS NULL THEN 1
            ELSE 0
        END
    ) AS missing_volume_item_count,

    SUM(
        CASE
            WHEN product_category_name IS NULL THEN 1
            ELSE 0
        END
    ) AS missing_category_item_count,

    -- Representative seller:
    -- seller state belonging to the highest-priced item
    ARG_MAX(seller_state, price) AS primary_seller_state,

    -- Earliest and latest seller shipping limits
    MIN(shipping_limit_date) AS earliest_shipping_limit_date,
    MAX(shipping_limit_date) AS latest_shipping_limit_date

FROM enriched_order_items

GROUP BY order_id;