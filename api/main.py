"""FastAPI service for delivery predictions.

The API loads the saved classification and regression pipelines.

Each saved pipeline contains:

1. The fitted preprocessor.
2. The fitted machine-learning model.

A request supplies the original 47 features. The pipelines perform
preprocessing automatically before producing predictions.
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import MODEL_FEATURES  # noqa: E402


CLASSIFICATION_MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "classification"
    / "best_classification_pipeline.joblib"
)

CLASSIFICATION_METADATA_PATH = (
    PROJECT_ROOT
    / "models"
    / "classification"
    / "best_classification_metadata.json"
)

REGRESSION_MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "regression"
    / "best_regression_pipeline.joblib"
)


classification_pipeline = None
regression_pipeline = None
classification_threshold = 0.50


class PredictionRequest(BaseModel):
    """Original order features supplied to the API."""

    features: dict[str, Any] = Field(
        ...,
        description=(
            "Dictionary containing all required model features."
        ),
    )


class PredictionResponse(BaseModel):
    """Classification and regression prediction response."""

    late_delivery_probability: float
    late_delivery_prediction: int
    classification_threshold: float
    predicted_delivery_days: float


def load_saved_models() -> None:
    """Load fitted model pipelines and threshold."""

    global classification_pipeline
    global regression_pipeline
    global classification_threshold

    required_files = [
        CLASSIFICATION_MODEL_PATH,
        CLASSIFICATION_METADATA_PATH,
        REGRESSION_MODEL_PATH,
    ]

    missing_files = [
        str(file_path)
        for file_path in required_files
        if not file_path.exists()
    ]

    if missing_files:
        raise FileNotFoundError(
            f"Required model files are missing: {missing_files}"
        )

    classification_pipeline = joblib.load(
        CLASSIFICATION_MODEL_PATH
    )

    regression_pipeline = joblib.load(
        REGRESSION_MODEL_PATH
    )

    metadata = json.loads(
        CLASSIFICATION_METADATA_PATH.read_text(
            encoding="utf-8",
        )
    )

    classification_threshold = float(
        metadata.get(
            "classification_threshold",
            0.50,
        )
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models when the API starts."""

    load_saved_models()

    yield


app = FastAPI(
    title="Olist Delivery Prediction API",
    description=(
        "Predict whether an order will be delivered late and "
        "estimate its delivery duration."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def build_input_dataframe(
    features: dict[str, Any],
) -> pd.DataFrame:
    """Validate and convert one request into a model input."""

    missing_features = [
        feature
        for feature in MODEL_FEATURES
        if feature not in features
    ]

    if missing_features:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Required model features are missing.",
                "missing_features": missing_features,
            },
        )

    ordered_features = {
        feature: features[feature]
        for feature in MODEL_FEATURES
    }

    return pd.DataFrame(
        [ordered_features],
        columns=MODEL_FEATURES,
    )


@app.get("/")
def root() -> dict[str, str]:
    """Return basic API information."""

    return {
        "message": "Olist Delivery Prediction API",
        "documentation": "/docs",
        "health_check": "/health",
        "prediction_endpoint": "/predict",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Check whether model pipelines are loaded."""

    models_loaded = (
        classification_pipeline is not None
        and regression_pipeline is not None
    )

    return {
        "status": (
            "healthy"
            if models_loaded
            else "unhealthy"
        ),
        "classification_model_loaded":
            classification_pipeline is not None,
        "regression_model_loaded":
            regression_pipeline is not None,
        "classification_threshold":
            classification_threshold,
        "required_feature_count":
            len(MODEL_FEATURES),
    }


@app.get("/features")
def features() -> dict[str, Any]:
    """Return the feature names required by the API."""

    return {
        "feature_count": len(MODEL_FEATURES),
        "required_features": MODEL_FEATURES,
    }


@app.post(
    "/predict",
    response_model=PredictionResponse,
)
def predict(
    request: PredictionRequest,
) -> PredictionResponse:
    """Generate classification and regression predictions."""

    if (
        classification_pipeline is None
        or regression_pipeline is None
    ):
        raise HTTPException(
            status_code=503,
            detail="Model pipelines are not loaded.",
        )

    input_dataframe = build_input_dataframe(
        request.features
    )

    late_probability = float(
        classification_pipeline.predict_proba(
            input_dataframe
        )[0, 1]
    )

    late_prediction = int(
        late_probability
        >= classification_threshold
    )

    predicted_delivery_days = float(
        regression_pipeline.predict(
            input_dataframe
        )[0]
    )

    return PredictionResponse(
        late_delivery_probability=
            late_probability,
        late_delivery_prediction=
            late_prediction,
        classification_threshold=
            classification_threshold,
        predicted_delivery_days=
            predicted_delivery_days,
    )