import pandas as pd

from api import main
from src.features.feature_config import MODEL_FEATURES


def sample_features() -> dict:
    data = pd.read_parquet(
        "data/processed/splits/validation.parquet",
        columns=MODEL_FEATURES,
    )
    return data.iloc[0][MODEL_FEATURES].to_dict()


def test_improved_models_load_and_health_is_healthy() -> None:
    main.load_saved_models()

    response = main.health()

    assert response["status"] == "healthy"
    assert response["classification_model_loaded"] is True
    assert response["regression_model_loaded"] is True
    assert response["required_feature_count"] == 47


def test_predict_preserves_raw_api_schema() -> None:
    main.load_saved_models()

    response = main.predict(main.PredictionRequest(features=sample_features()))

    assert 0.0 <= response.late_delivery_probability <= 1.0
    assert response.late_delivery_prediction in {0, 1}
    assert response.classification_threshold == 0.65
    assert response.predicted_delivery_days > 0