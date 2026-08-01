import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.pipeline import Pipeline

from src.features.improved_feature_engineering import ImprovedFeatureEngineer


def make_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_state": ["RJ", "RJ", "SP"],
            "primary_seller_state": ["SP", "SP", "MG"],
            "same_state_delivery": [0, 0, 1],
            "purchase_month": [1, 6, 12],
            "purchase_weekday": [0, 3, 6],
            "purchase_hour": [2, 12, 23],
            "approval_delay_hours": [2.0, 4.0, 1.0],
            "promised_delivery_days": [10.0, 0.0, 20.0],
            "seller_shipping_window_days": [3.0, 2.0, 5.0],
            "item_count": [2, 0, 1],
            "unique_product_count": [2, 0, 1],
            "unique_seller_count": [1, 0, 1],
            "unique_category_count": [2, 0, 1],
            "total_item_price": [100.0, 0.0, 20.0],
            "total_freight": [20.0, 5.0, 2.0],
            "total_product_weight_g": [2000.0, 0.0, 100.0],
            "total_product_volume_cm3": [1000.0, 0.0, 50.0],
            "average_product_photos": [4.0, np.nan, 1.0],
            "total_payment_value": [120.0, 0.0, 22.0],
            "maximum_installments": [3, 0, 1],
        }
    )


def test_transform_preserves_raw_columns_and_handles_zero_denominators() -> None:
    features = make_features()
    transformed = ImprovedFeatureEngineer().fit_transform(features)

    pd.testing.assert_frame_equal(transformed[features.columns], features)
    assert transformed.loc[0, "seller_customer_route"] == "SP->RJ"
    assert transformed.loc[0, "route_frequency"] == 2 / 3
    assert transformed.loc[0, "photos_per_item"] == 4.0
    assert np.isnan(transformed.loc[1, "price_per_item"])
    assert np.isnan(transformed.loc[1, "shipping_window_to_promised_ratio"])
    numeric = transformed.select_dtypes(include=[np.number])
    assert not np.isinf(numeric.to_numpy()).any()


def test_unseen_route_gets_zero_training_frequency() -> None:
    features = make_features()
    engineer = ImprovedFeatureEngineer().fit(features)
    unseen = features.iloc[[0]].copy()
    unseen["customer_state"] = "AM"

    transformed = engineer.transform(unseen)

    assert transformed.loc[0, "seller_customer_route"] == "SP->AM"
    assert transformed.loc[0, "route_frequency"] == 0.0


def test_transformer_drops_forbidden_input_columns() -> None:
    features = make_features().assign(late_delivery=1, order_id="order-1")

    transformed = ImprovedFeatureEngineer().fit_transform(features)

    assert "late_delivery" not in transformed.columns
    assert "order_id" not in transformed.columns


def test_transformer_is_pipeline_compatible() -> None:
    features = make_features()
    pipeline = Pipeline(
        steps=[
            ("features", ImprovedFeatureEngineer()),
            ("model", DummyRegressor(strategy="mean")),
        ]
    )

    pipeline.fit(features, np.array([5.0, 6.0, 7.0]))

    assert pipeline.predict(features).shape == (len(features),)