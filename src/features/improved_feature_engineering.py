"""Leakage-safe feature engineering for the existing 47-feature API contract."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted

from src.features.feature_config import CATEGORICAL_FEATURES, MODEL_FEATURES


DERIVED_CATEGORICAL_FEATURES = [
    "seller_customer_route",
]

DERIVED_NUMERICAL_FEATURES = [
    "is_weekend_purchase",
    "is_night_purchase",
    "is_business_hours",
    "month_sin",
    "month_cos",
    "weekday_sin",
    "weekday_cos",
    "hour_sin",
    "hour_cos",
    "is_multi_item_order",
    "is_multi_product_order",
    "is_multi_seller_order",
    "is_multi_category_order",
    "items_per_seller",
    "products_per_seller",
    "categories_per_seller",
    "price_per_item",
    "freight_per_item",
    "freight_per_kg",
    "freight_to_payment_ratio",
    "payment_to_item_price_ratio",
    "installment_value",
    "is_installment_payment",
    "weight_per_item",
    "volume_per_item",
    "density_g_per_cm3",
    "photos_per_item",
    "shipping_window_to_promised_ratio",
    "promised_minus_shipping_window",
    "approval_delay_to_promised_ratio",
    "cross_state_delivery",
    "route_frequency",
    "log1p_total_item_price",
    "log1p_total_freight",
    "log1p_total_weight",
    "log1p_total_volume",
    "log1p_payment_value",
]


def get_improved_feature_roles(
    columns: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Return categorical and numeric feature names present in transformed data."""

    column_set = set(columns)
    categorical = [
        column
        for column in CATEGORICAL_FEATURES + DERIVED_CATEGORICAL_FEATURES
        if column in column_set
    ]
    numerical = [
        column
        for column in columns
        if column not in categorical
    ]
    return categorical, numerical


class ImprovedFeatureEngineer(BaseEstimator, TransformerMixin):
    """Derive leakage-safe features and train-only route frequencies from raw inputs.

    The transformer accepts a pandas DataFrame containing any subset of the
    existing API fields. A derived feature is added only when all of its source
    columns are available. ``route_frequency`` is learned exclusively in
    ``fit`` and unseen routes receive 0.0 during ``transform``.
    """

    @staticmethod
    def _require_dataframe(X: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(X, pd.DataFrame):
            raise TypeError(
                "ImprovedFeatureEngineer requires a pandas DataFrame with named columns."
            )
        return X

    @staticmethod
    def _safe_divide(
        numerator: pd.Series,
        denominator: pd.Series,
    ) -> pd.Series:
        denominator_values = pd.to_numeric(denominator, errors="coerce")
        numerator_values = pd.to_numeric(numerator, errors="coerce")
        result = numerator_values.div(denominator_values.where(denominator_values != 0))
        return result.replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _route_series(dataframe: pd.DataFrame) -> pd.Series | None:
        required_columns = {"primary_seller_state", "customer_state"}
        if not required_columns.issubset(dataframe.columns):
            return None
        return (
            dataframe["primary_seller_state"].fillna("<missing>").astype(str)
            + "->"
            + dataframe["customer_state"].fillna("<missing>").astype(str)
        )

    @staticmethod
    def _add_if_available(
        dataframe: pd.DataFrame,
        name: str,
        required_columns: set[str],
        operation,
    ) -> None:
        if required_columns.issubset(dataframe.columns):
            values = operation()
            dataframe[name] = pd.Series(values, index=dataframe.index).replace(
                [np.inf, -np.inf],
                np.nan,
            )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series | np.ndarray | None = None,
    ) -> "ImprovedFeatureEngineer":
        """Learn route frequencies from training features only."""

        dataframe = self._require_dataframe(X)
        dataframe = dataframe.loc[
            :,
            [column for column in dataframe.columns if column in MODEL_FEATURES],
        ]
        self.feature_names_in_ = np.asarray(dataframe.columns, dtype=object)
        route = self._route_series(dataframe)
        if route is None or route.empty:
            self.route_frequency_ = {}
        else:
            self.route_frequency_ = route.value_counts(normalize=True).to_dict()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return raw inputs plus derived features without modifying the caller data."""

        check_is_fitted(self, ["feature_names_in_", "route_frequency_"])
        source = self._require_dataframe(X)
        source = source.loc[
            :,
            [column for column in source.columns if column in MODEL_FEATURES],
        ]
        result = source.copy()

        self._add_if_available(
            result,
            "is_weekend_purchase",
            {"purchase_weekday"},
            lambda: result["purchase_weekday"].isin([0, 6]).astype("int8"),
        )
        self._add_if_available(
            result,
            "is_night_purchase",
            {"purchase_hour"},
            lambda: ((result["purchase_hour"] < 6) | (result["purchase_hour"] >= 22)).astype("int8"),
        )
        self._add_if_available(
            result,
            "is_business_hours",
            {"purchase_hour"},
            lambda: ((result["purchase_hour"] >= 9) & (result["purchase_hour"] < 18)).astype("int8"),
        )

        for source_column, period, sine_name, cosine_name in [
            ("purchase_month", 12, "month_sin", "month_cos"),
            ("purchase_weekday", 7, "weekday_sin", "weekday_cos"),
            ("purchase_hour", 24, "hour_sin", "hour_cos"),
        ]:
            if source_column in result.columns:
                values = pd.to_numeric(result[source_column], errors="coerce")
                if source_column == "purchase_month":
                    values = values - 1
                angle = 2 * np.pi * values / period
                result[sine_name] = np.sin(angle)
                result[cosine_name] = np.cos(angle)

        for source_column, feature_name in [
            ("item_count", "is_multi_item_order"),
            ("unique_product_count", "is_multi_product_order"),
            ("unique_seller_count", "is_multi_seller_order"),
            ("unique_category_count", "is_multi_category_order"),
        ]:
            self._add_if_available(
                result,
                feature_name,
                {source_column},
                lambda source_column=source_column: (result[source_column] > 1).astype("int8"),
            )

        ratio_features = [
            ("items_per_seller", "item_count", "unique_seller_count"),
            ("products_per_seller", "unique_product_count", "unique_seller_count"),
            ("categories_per_seller", "unique_category_count", "unique_seller_count"),
            ("price_per_item", "total_item_price", "item_count"),
            ("freight_per_item", "total_freight", "item_count"),
            ("freight_to_payment_ratio", "total_freight", "total_payment_value"),
            ("payment_to_item_price_ratio", "total_payment_value", "total_item_price"),
            ("installment_value", "total_payment_value", "maximum_installments"),
            ("weight_per_item", "total_product_weight_g", "item_count"),
            ("volume_per_item", "total_product_volume_cm3", "item_count"),
            ("density_g_per_cm3", "total_product_weight_g", "total_product_volume_cm3"),
            ("shipping_window_to_promised_ratio", "seller_shipping_window_days", "promised_delivery_days"),
            ("approval_delay_to_promised_ratio", "approval_delay_hours", "promised_delivery_days"),
        ]
        for feature_name, numerator, denominator in ratio_features:
            self._add_if_available(
                result,
                feature_name,
                {numerator, denominator},
                lambda numerator=numerator, denominator=denominator: self._safe_divide(
                    result[numerator],
                    result[denominator],
                ),
            )

        self._add_if_available(
            result,
            "freight_per_kg",
            {"total_freight", "total_product_weight_g"},
            lambda: self._safe_divide(
                result["total_freight"],
                pd.to_numeric(result["total_product_weight_g"], errors="coerce") / 1000,
            ),
        )
        self._add_if_available(
            result,
            "photos_per_item",
            {"average_product_photos"},
            lambda: result["average_product_photos"],
        )
        self._add_if_available(
            result,
            "is_installment_payment",
            {"maximum_installments"},
            lambda: (result["maximum_installments"] > 1).astype("int8"),
        )
        self._add_if_available(
            result,
            "promised_minus_shipping_window",
            {"promised_delivery_days", "seller_shipping_window_days"},
            lambda: result["promised_delivery_days"] - result["seller_shipping_window_days"],
        )
        self._add_if_available(
            result,
            "cross_state_delivery",
            {"same_state_delivery"},
            lambda: result["same_state_delivery"].eq(0).astype("int8"),
        )

        route = self._route_series(result)
        if route is not None:
            result["seller_customer_route"] = route
            result["route_frequency"] = route.map(self.route_frequency_).fillna(0.0)

        for feature_name, source_column in [
            ("log1p_total_item_price", "total_item_price"),
            ("log1p_total_freight", "total_freight"),
            ("log1p_total_weight", "total_product_weight_g"),
            ("log1p_total_volume", "total_product_volume_cm3"),
            ("log1p_payment_value", "total_payment_value"),
        ]:
            self._add_if_available(
                result,
                feature_name,
                {source_column},
                lambda source_column=source_column: np.log1p(
                    pd.to_numeric(result[source_column], errors="coerce").where(
                        pd.to_numeric(result[source_column], errors="coerce") >= 0
                    )
                ),
            )

        return result.replace([np.inf, -np.inf], np.nan)

    def get_feature_names_out(
        self,
        input_features: Sequence[str] | None = None,
    ) -> np.ndarray:
        """Return input names plus features derivable from the supplied schema."""

        check_is_fitted(self, "feature_names_in_")
        columns = list(input_features if input_features is not None else self.feature_names_in_)
        transformed = self.transform(pd.DataFrame(columns=columns))
        return np.asarray(transformed.columns, dtype=object)