-- ============================================================
-- Aggregate multiple payment rows into one row per order
-- Grain of source: one payment record per row
-- Grain of output: one order per row
-- ============================================================

CREATE OR REPLACE TABLE payment_features AS
SELECT
    order_id,

    -- Number of payment records
    COUNT(*) AS payment_count,

    -- Number of different payment methods used
    COUNT(DISTINCT payment_type) AS payment_type_count,

    -- Payment-value features
    SUM(payment_value) AS total_payment_value,
    AVG(payment_value) AS average_payment_value,
    MIN(payment_value) AS minimum_payment_value,
    MAX(payment_value) AS maximum_payment_value,

    -- Instalment features
    MAX(payment_installments) AS maximum_installments,
    AVG(payment_installments) AS average_installments,

    -- Payment method representing the largest payment amount
    ARG_MAX(payment_type, payment_value)
        AS primary_payment_type,

    -- Amount associated with the primary payment method
    MAX(payment_value)
        AS primary_payment_value,

    -- Payment-method indicators
    MAX(
        CASE
            WHEN payment_type = 'credit_card' THEN 1
            ELSE 0
        END
    ) AS used_credit_card,

    MAX(
        CASE
            WHEN payment_type = 'voucher' THEN 1
            ELSE 0
        END
    ) AS used_voucher,

    MAX(
        CASE
            WHEN payment_type = 'boleto' THEN 1
            ELSE 0
        END
    ) AS used_boleto,

    MAX(
        CASE
            WHEN payment_type = 'debit_card' THEN 1
            ELSE 0
        END
    ) AS used_debit_card

FROM payments

GROUP BY order_id;