"""Evaluate the frozen improved models once on the held-out test split."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    median_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
    REGRESSION_TARGET,
)


TEST_PATH = PROJECT_ROOT / "data" / "processed" / "splits" / "test.parquet"
MODEL_DIRECTORY = PROJECT_ROOT / "models" / "improved"
CLASSIFICATION_PIPELINE_PATH = MODEL_DIRECTORY / "classification_pipeline.joblib"
CLASSIFICATION_METADATA_PATH = MODEL_DIRECTORY / "classification_metadata.json"
REGRESSION_PIPELINE_PATH = MODEL_DIRECTORY / "regression_pipeline.joblib"
CLASSIFICATION_REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "improved" / "classification"
REGRESSION_REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "improved" / "regression"


def within_error(y_true: pd.Series, predictions: np.ndarray, days: float) -> float:
    """Return the fraction of predictions within the specified absolute error."""

    return float(np.mean(np.abs(y_true.to_numpy() - predictions) <= days))


def main() -> None:
    """Score frozen selected models once, with no fitting, tuning, or selection."""

    required_files = [
        TEST_PATH,
        CLASSIFICATION_PIPELINE_PATH,
        CLASSIFICATION_METADATA_PATH,
        REGRESSION_PIPELINE_PATH,
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required final evaluation files are missing: {missing}")

    classification_metadata = json.loads(CLASSIFICATION_METADATA_PATH.read_text(encoding="utf-8"))
    classification_threshold = float(classification_metadata["classification_threshold"])
    classification_pipeline = joblib.load(CLASSIFICATION_PIPELINE_PATH)
    regression_pipeline = joblib.load(REGRESSION_PIPELINE_PATH)

    test_data = pd.read_parquet(TEST_PATH)
    X_test = test_data[MODEL_FEATURES]
    y_classification = test_data[CLASSIFICATION_TARGET]
    y_regression = test_data[REGRESSION_TARGET]

    prediction_start = time.perf_counter()
    late_probabilities = classification_pipeline.predict_proba(X_test)[:, 1]
    predicted_delivery_days = regression_pipeline.predict(X_test)
    total_inference_seconds = time.perf_counter() - prediction_start
    late_predictions = (late_probabilities >= classification_threshold).astype(int)
    true_negative, false_positive, false_negative, true_positive = confusion_matrix(
        y_classification,
        late_predictions,
        labels=[0, 1],
    ).ravel()

    classification_metrics = {
        "evaluation_split": "test",
        "model_name": classification_metadata["model_name"],
        "classification_threshold": classification_threshold,
        "positive_rate_pr_auc_baseline": float(y_classification.mean()),
        "pr_auc": float(average_precision_score(y_classification, late_probabilities)),
        "roc_auc": float(roc_auc_score(y_classification, late_probabilities)),
        "precision": float(precision_score(y_classification, late_predictions, zero_division=0)),
        "recall": float(recall_score(y_classification, late_predictions, zero_division=0)),
        "f1_score": float(f1_score(y_classification, late_predictions, zero_division=0)),
        "accuracy": float(accuracy_score(y_classification, late_predictions)),
        "true_negative": int(true_negative),
        "false_positive": int(false_positive),
        "false_negative": int(false_negative),
        "true_positive": int(true_positive),
        "inference_seconds_for_both_models": float(total_inference_seconds),
        "inference_ms_per_order_for_both_models": float(total_inference_seconds * 1_000 / len(X_test)),
        "test_evaluated_once": True,
    }
    regression_metrics = {
        "evaluation_split": "test",
        "model_name": "hist_gradient_boosting",
        "mae": float(mean_absolute_error(y_regression, predicted_delivery_days)),
        "rmse": float(np.sqrt(mean_squared_error(y_regression, predicted_delivery_days))),
        "median_absolute_error": float(median_absolute_error(y_regression, predicted_delivery_days)),
        "r2_score": float(r2_score(y_regression, predicted_delivery_days)),
        "within_2_days": within_error(y_regression, predicted_delivery_days, 2.0),
        "within_5_days": within_error(y_regression, predicted_delivery_days, 5.0),
        "within_7_days": within_error(y_regression, predicted_delivery_days, 7.0),
        "test_evaluated_once": True,
    }
    predictions = pd.DataFrame(
        {
            "order_id": test_data["order_id"],
            "late_delivery_actual": y_classification,
            "late_delivery_probability": late_probabilities,
            "late_delivery_prediction": late_predictions,
            "actual_delivery_days": y_regression,
            "predicted_delivery_days": predicted_delivery_days,
            "absolute_delivery_error_days": np.abs(y_regression.to_numpy() - predicted_delivery_days),
        }
    )

    CLASSIFICATION_REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    REGRESSION_REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (CLASSIFICATION_REPORT_DIRECTORY / "final_test_metrics.json").write_text(
        json.dumps(classification_metrics, indent=2),
        encoding="utf-8",
    )
    (REGRESSION_REPORT_DIRECTORY / "final_test_metrics.json").write_text(
        json.dumps(regression_metrics, indent=2),
        encoding="utf-8",
    )
    predictions.to_csv(CLASSIFICATION_REPORT_DIRECTORY / "final_test_predictions.csv", index=False)
    predictions.to_csv(REGRESSION_REPORT_DIRECTORY / "final_test_predictions.csv", index=False)

    print("Final frozen-model test evaluation completed once.")
    print(json.dumps({"classification": classification_metrics, "regression": regression_metrics}, indent=2))


if __name__ == "__main__":
    main()