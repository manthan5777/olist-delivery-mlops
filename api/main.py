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
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from redis import Redis
from redis.exceptions import RedisError
from datetime import datetime, timezone
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import MODEL_FEATURES  # noqa: E402


# --------------------------------------------------
# MODEL FILE LOCATIONS
# --------------------------------------------------

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
    / "improved"
    / "regression_pipeline.joblib"
)


# --------------------------------------------------
# REDIS CONFIGURATION
# --------------------------------------------------

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

redis_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

QUEUE_NAME = "olist:jobs"
JOB_KEY_PREFIX = "olist:job:"
JOB_TTL_SECONDS = 3600

# --------------------------------------------------
# LOADED MODEL OBJECTS
# --------------------------------------------------

classification_pipeline = None
regression_pipeline = None
classification_threshold = 0.50


# --------------------------------------------------
# PYDANTIC REQUEST AND RESPONSE MODELS
# --------------------------------------------------

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

class JobCreateResponse(BaseModel):
    """Response returned after creating a background job."""

    job_id: str
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    """Current state of a background job."""

    job_id: str
    status: str
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None
    error: str | None = None
    
# --------------------------------------------------
# MODEL LOADING
# --------------------------------------------------

def load_saved_models() -> None:
    """Load fitted model pipelines and classification threshold."""

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


# --------------------------------------------------
# FASTAPI APPLICATION LIFESPAN
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models when the FastAPI application starts."""

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


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def build_input_dataframe(
    features: dict[str, Any],
) -> pd.DataFrame:
    """Validate and convert one request into model input."""

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


def redis_is_connected() -> bool:
    """Check whether the Redis server is reachable."""

    try:
        return bool(redis_client.ping())

    except RedisError:
        return False


# --------------------------------------------------
# API ENDPOINTS
# --------------------------------------------------

@app.get("/")
def root() -> dict[str, str]:
    """Return basic API information."""

    return {
        "message": "Olist Delivery Prediction API",
        "documentation": "/docs",
        "health_check": "/health",
        "prediction_endpoint": "/predict",
    }

@app.post(
    "/jobs/demo",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_demo_job() -> JobCreateResponse:
    """Create a demonstration background job."""

    job_id = str(uuid4())
    job_key = f"{JOB_KEY_PREFIX}{job_id}"

    try:
        redis_client.hset(
            job_key,
            mapping={
                "status": "queued",
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

        redis_client.expire(
            job_key,
            JOB_TTL_SECONDS,
        )

        redis_client.lpush(
            QUEUE_NAME,
            job_id,
        )

    except RedisError as error:
        raise HTTPException(
            status_code=503,
            detail="Background-job service is unavailable.",
        ) from error

    return JobCreateResponse(
        job_id=job_id,
        status="queued",
        status_url=f"/jobs/{job_id}",
    )


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
def get_job_status(
    job_id: str,
) -> JobStatusResponse:
    """Return the current state of a background job."""

    job_key = f"{JOB_KEY_PREFIX}{job_id}"

    try:
        job_data = redis_client.hgetall(job_key)

    except RedisError as error:
        raise HTTPException(
            status_code=503,
            detail="Background-job service is unavailable.",
        ) from error

    if not job_data:
        raise HTTPException(
            status_code=404,
            detail="Job was not found or has expired.",
        )

    return JobStatusResponse(
        job_id=job_id,
        status=job_data.get("status", "unknown"),
        created_at=job_data.get("created_at"),
        started_at=job_data.get("started_at"),
        completed_at=job_data.get("completed_at"),
        result=job_data.get("result"),
        error=job_data.get("error"),
    )

@app.get("/health")
def health() -> dict[str, Any]:
    """Check models and Redis connectivity."""

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
        "redis_connected":
            redis_is_connected(),
        "redis_url":
            REDIS_URL,
    }


@app.get("/features")
def features() -> dict[str, Any]:
    """Return feature names required by the API."""

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
        late_delivery_probability=late_probability,
        late_delivery_prediction=late_prediction,
        classification_threshold=classification_threshold,
        predicted_delivery_days=predicted_delivery_days,
    )

