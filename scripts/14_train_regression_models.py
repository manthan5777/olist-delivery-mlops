"""Train and compare delivery-duration regression models.

Flow:

Raw training features
    -> preprocessing fits on training data
    -> transformed training features
    -> regression model training

Raw validation features
    -> training-fitted preprocessing
    -> transformed validation features
    -> delivery-day predictions

The test dataset is not used.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
)
from sklearn.pipeline import Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    MODEL_FEATURES,
    REGRESSION_TARGET,
)

from src.models.regression_models import (  # noqa: E402
    get_regression_models,
)

from src.preprocessing.build_preprocessor import (  # noqa: E402
    build_preprocessor,
)


SPLIT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
)

TRAIN_PATH = (
    SPLIT_DIRECTORY
    / "train.parquet"
)

VALIDATION_PATH = (
    SPLIT_DIRECTORY
    / "validation.parquet"
)

MODEL_DIRECTORY = (
    PROJECT_ROOT
    / "models"
    / "regression"
)

REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "regression"
)

METRICS_CSV_PATH = (
    REPORT_DIRECTORY
    / "validation_metrics.csv"
)

METRICS_JSON_PATH = (
    REPORT_DIRECTORY
    / "validation_metrics.json"
)

BEST_MODEL_PATH = (
    MODEL_DIRECTORY
    / "best_regression_pipeline.joblib"
)

BEST_MODEL_METADATA_PATH = (
    MODEL_DIRECTORY
    / "best_regression_metadata.json"
)


def load_dataset(
    file_path: Path,
) -> pd.DataFrame:
    """Load one Parquet dataset."""

    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {file_path}"
        )

    return pd.read_parquet(file_path)


def create_model_pipeline(
    model,
) -> Pipeline:
    """Connect preprocessing and regression model."""

    return Pipeline(
        steps=[
            (
                "preprocessor",
                build_preprocessor(),
            ),
            (
                "model",
                model,
            ),
        ]
    )


def percentage_within_error(
    actual_values: pd.Series,
    predicted_values: np.ndarray,
    allowed_error: float,
) -> float:
    """Calculate predictions within an allowed number of days."""

    absolute_errors = np.abs(
        actual_values.to_numpy()
        - predicted_values
    )

    return float(
        np.mean(
            absolute_errors <= allowed_error
        )
    )


def evaluate_regressor(
    model_name: str,
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_validation: pd.DataFrame,
    y_validation: pd.Series,
) -> dict:
    """Train and validate one regression pipeline."""

    print("\n" + "=" * 100)
    print(f"TRAINING: {model_name}")
    print("=" * 100)

    training_start = time.perf_counter()

    pipeline.fit(
        X_train,
        y_train,
    )

    training_seconds = (
        time.perf_counter()
        - training_start
    )

    prediction_start = time.perf_counter()

    validation_predictions = pipeline.predict(
        X_validation
    )

    prediction_seconds = (
        time.perf_counter()
        - prediction_start
    )

    mae = mean_absolute_error(
        y_validation,
        validation_predictions,
    )

    mse = mean_squared_error(
        y_validation,
        validation_predictions,
    )

    rmse = float(
        np.sqrt(mse)
    )

    median_ae = median_absolute_error(
        y_validation,
        validation_predictions,
    )

    r2 = r2_score(
        y_validation,
        validation_predictions,
    )

    metrics = {
        "model_name": model_name,

        "mae": float(mae),
        "rmse": rmse,
        "median_absolute_error": float(
            median_ae
        ),
        "r2_score": float(r2),

        "within_2_days": percentage_within_error(
            actual_values=y_validation,
            predicted_values=validation_predictions,
            allowed_error=2.0,
        ),

        "within_5_days": percentage_within_error(
            actual_values=y_validation,
            predicted_values=validation_predictions,
            allowed_error=5.0,
        ),

        "within_7_days": percentage_within_error(
            actual_values=y_validation,
            predicted_values=validation_predictions,
            allowed_error=7.0,
        ),

        "minimum_prediction": float(
            validation_predictions.min()
        ),

        "maximum_prediction": float(
            validation_predictions.max()
        ),

        "average_prediction": float(
            validation_predictions.mean()
        ),

        "training_seconds": float(
            training_seconds
        ),

        "prediction_seconds": float(
            prediction_seconds
        ),

        "prediction_ms_per_order": float(
            prediction_seconds
            * 1000
            / len(X_validation)
        ),
    }

    print(
        f"MAE:             "
        f"{metrics['mae']:.4f} days"
    )

    print(
        f"RMSE:            "
        f"{metrics['rmse']:.4f} days"
    )

    print(
        f"Median AE:       "
        f"{metrics['median_absolute_error']:.4f} days"
    )

    print(
        f"R² score:        "
        f"{metrics['r2_score']:.4f}"
    )

    print(
        f"Within ±2 days:  "
        f"{100 * metrics['within_2_days']:.2f}%"
    )

    print(
        f"Within ±5 days:  "
        f"{100 * metrics['within_5_days']:.2f}%"
    )

    print(
        f"Within ±7 days:  "
        f"{100 * metrics['within_7_days']:.2f}%"
    )

    print(
        f"\nTraining time:   "
        f"{training_seconds:.2f} seconds"
    )

    print(
        f"Prediction time: "
        f"{prediction_seconds:.4f} seconds"
    )

    return metrics


def save_validation_results(
    results: list[dict],
) -> pd.DataFrame:
    """Save and display validation metrics."""

    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    results_dataframe = pd.DataFrame(
        results
    ).sort_values(
        by="mae",
        ascending=True,
    )

    results_dataframe.to_csv(
        METRICS_CSV_PATH,
        index=False,
    )

    METRICS_JSON_PATH.write_text(
        json.dumps(
            results,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 100)
    print("VALIDATION REGRESSION COMPARISON")
    print("=" * 100)

    display_columns = [
        "model_name",
        "mae",
        "rmse",
        "median_absolute_error",
        "r2_score",
        "within_2_days",
        "within_5_days",
        "within_7_days",
        "training_seconds",
    ]

    display_dataframe = results_dataframe[
        display_columns
    ].copy()

    display_dataframe[
        "within_2_days"
    ] *= 100

    display_dataframe[
        "within_5_days"
    ] *= 100

    display_dataframe[
        "within_7_days"
    ] *= 100

    print(
        display_dataframe.to_string(
            index=False,
            formatters={
                "mae": "{:.4f}".format,
                "rmse": "{:.4f}".format,
                "median_absolute_error":
                    "{:.4f}".format,
                "r2_score": "{:.4f}".format,
                "within_2_days":
                    "{:.2f}%".format,
                "within_5_days":
                    "{:.2f}%".format,
                "within_7_days":
                    "{:.2f}%".format,
                "training_seconds":
                    "{:.2f}".format,
            },
        )
    )

    return results_dataframe


def save_best_model(
    best_model_name: str,
    best_pipeline: Pipeline,
    best_metrics: dict,
) -> None:
    """Save the best fitted regression pipeline."""

    MODEL_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        best_pipeline,
        BEST_MODEL_PATH,
    )

    metadata = {
        "model_name": best_model_name,
        "selection_metric": "validation_mae",
        "target": REGRESSION_TARGET,
        "raw_feature_count": len(
            MODEL_FEATURES
        ),
        "validation_metrics": best_metrics,
        "model_path": str(
            BEST_MODEL_PATH
        ),
    }

    BEST_MODEL_METADATA_PATH.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Train and compare regression pipelines."""

    print("=" * 100)
    print("REGRESSION MODEL TRAINING")
    print("=" * 100)

    train_data = load_dataset(
        TRAIN_PATH
    )

    validation_data = load_dataset(
        VALIDATION_PATH
    )

    X_train = train_data[
        MODEL_FEATURES
    ]

    y_train = train_data[
        REGRESSION_TARGET
    ]

    X_validation = validation_data[
        MODEL_FEATURES
    ]

    y_validation = validation_data[
        REGRESSION_TARGET
    ]

    print(
        f"\nTraining rows:   "
        f"{len(X_train):,}"
    )

    print(
        f"Validation rows: "
        f"{len(X_validation):,}"
    )

    print(
        f"Input features:  "
        f"{len(MODEL_FEATURES)}"
    )

    print(
        f"Training average delivery: "
        f"{y_train.mean():.2f} days"
    )

    print(
        f"Validation average delivery: "
        f"{y_validation.mean():.2f} days"
    )

    models = get_regression_models()

    results = []

    best_pipeline = None
    best_model_name = None
    best_metrics = None
    best_mae = float("inf")

    for model_name, model in models.items():
        pipeline = create_model_pipeline(
            model
        )

        metrics = evaluate_regressor(
            model_name=model_name,
            pipeline=pipeline,
            X_train=X_train,
            y_train=y_train,
            X_validation=X_validation,
            y_validation=y_validation,
        )

        results.append(metrics)

        if metrics["mae"] < best_mae:
            best_mae = metrics["mae"]
            best_pipeline = pipeline
            best_model_name = model_name
            best_metrics = metrics

    save_validation_results(
        results
    )

    if (
        best_pipeline is None
        or best_model_name is None
        or best_metrics is None
    ):
        raise RuntimeError(
            "No regression model was selected."
        )

    save_best_model(
        best_model_name=best_model_name,
        best_pipeline=best_pipeline,
        best_metrics=best_metrics,
    )

    print("\n" + "=" * 100)
    print("REGRESSION TRAINING COMPLETED")
    print("=" * 100)

    print(
        f"\nBest model: "
        f"{best_model_name}"
    )

    print(
        f"Best validation MAE: "
        f"{best_mae:.4f} days"
    )

    print(
        "\nSaved complete fitted pipeline to:\n"
        f"{BEST_MODEL_PATH}"
    )

    print(
        "\nThe test dataset was not used."
    )


if __name__ == "__main__":
    main()