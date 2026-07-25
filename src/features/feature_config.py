"""Central configuration for model features and target columns.

This file defines:

- columns used only for tracking,
- classification and regression targets,
- columns used only for analysis,
- categorical model features,
- numerical model features,
- columns that must never be used as model inputs.
"""


# ============================================================
# Tracking columns
# ============================================================
# These columns identify orders and customers.
# We keep them for tracing records, but do not train models on them.

TRACKING_COLUMNS = [
    "order_id",
    "customer_id",
    "customer_unique_id",
    "order_purchase_timestamp",
    "order_approved_at",
]


# ============================================================
# Target columns
# ============================================================
# Classification target:
# 0 = delivered on time
# 1 = delivered late

CLASSIFICATION_TARGET = "late_delivery"


# Regression target:
# Total number of days from purchase to delivery.

REGRESSION_TARGET = "actual_delivery_days"


# ============================================================
# Analysis-only columns
# ============================================================
# These columns are useful for reports and analysis,
# but they are known only after delivery has happened.

ANALYSIS_ONLY_COLUMNS = [
    "lateness_days",
]


# ============================================================
# Categorical model features
# ============================================================
# These contain categories rather than continuous measurements.
# They will later be converted into numerical form using encoding.

CATEGORICAL_FEATURES = [
    "customer_state",
    "primary_seller_state",
    "primary_payment_type",
    "purchase_year",
    "purchase_month",
    "purchase_weekday",
    "purchase_hour",
]


# ============================================================
# Numerical and binary model features
# ============================================================
# Numerical features contain amounts, counts, measurements,
# durations or ratios.
#
# Binary features also belong here because they contain 0 or 1.

NUMERICAL_FEATURES = [
    # Location relationship
    "same_state_delivery",

    # Time-related features
    "approval_delay_hours",
    "promised_delivery_days",
    "seller_shipping_window_days",

    # Order-item counts
    "item_count",
    "unique_product_count",
    "unique_seller_count",
    "unique_seller_state_count",
    "unique_category_count",

    # Price features
    "total_item_price",
    "average_item_price",
    "minimum_item_price",
    "maximum_item_price",

    # Freight features
    "total_freight",
    "average_freight_per_item",
    "maximum_freight_per_item",
    "freight_to_price_ratio",

    # Weight features
    "total_product_weight_g",
    "average_product_weight_g",
    "maximum_product_weight_g",

    # Volume features
    "total_product_volume_cm3",
    "average_product_volume_cm3",
    "maximum_product_volume_cm3",

    # Product listing features
    "average_product_photos",
    "maximum_product_photos",

    # Missing-information indicators
    "missing_weight_item_count",
    "missing_volume_item_count",
    "missing_category_item_count",

    # Payment features
    "payment_count",
    "payment_type_count",
    "total_payment_value",
    "average_payment_value",
    "minimum_payment_value",
    "maximum_payment_value",

    # Instalment features
    "maximum_installments",
    "average_installments",

    # Binary payment-method indicators
    "used_credit_card",
    "used_voucher",
    "used_boleto",
    "used_debit_card",
]


# ============================================================
# Complete model feature list
# ============================================================

MODEL_FEATURES = (
    CATEGORICAL_FEATURES
    + NUMERICAL_FEATURES
)


# ============================================================
# Forbidden model columns
# ============================================================
# These columns must never be included as model inputs.

FORBIDDEN_MODEL_COLUMNS = (
    TRACKING_COLUMNS
    + ANALYSIS_ONLY_COLUMNS
    + [
        CLASSIFICATION_TARGET,
        REGRESSION_TARGET,
    ]
)