"""Evaluate the final classification pipeline on untouched test data.

This script:

1. Loads the selected fitted classification pipeline.
2. Loads the threshold selected using validation data.
3. Loads the untouched test dataset.
4. Generates late-delivery probabilities.
5. Converts probabilities into predictions using the selected threshold.
6. Calculates final test metrics.
7. Saves test predictions, metrics and charts.

The model and threshold are not changed in this step.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
)


TEST_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
    / "test.parquet"
)

MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "classification"
    / "best_classification_pipeline.joblib"
)

MODEL_METADATA_PATH = (
    PROJECT_ROOT
    / "models"
    / "classification"
    / "best_classification_metadata.json"
)

REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "classification"
)

TEST_METRICS_PATH = (
    REPORT_DIRECTORY
    / "test_metrics.json"
)

TEST_PREDICTIONS_PATH = (
    REPORT_DIRECTORY
    / "test_predictions.parquet"
)

CONFUSION_MATRIX_PATH = (
    REPORT_DIRECTORY
    / "test_confusion_matrix.png"
)

PR_CURVE_PATH = (
    REPORT_DIRECTORY
    / "test_precision_recall_curve.png"
)


def load_test_data() -> pd.DataFrame:
    """Load the untouched test dataset."""

    if not TEST_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Test data not found: {TEST_DATA_PATH}"
        )

    return pd.read_parquet(TEST_DATA_PATH)


def load_model_pipeline():
    """Load the fitted preprocessing and classification pipeline."""

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model pipeline not found: {MODEL_PATH}"
        )

    return joblib.load(MODEL_PATH)


def load_selected_threshold() -> float:
    """Load the threshold selected using validation data."""

    if not MODEL_METADATA_PATH.exists():
        raise FileNotFoundError(
            "Model metadata was not found. Run threshold tuning first: "
            f"{MODEL_METADATA_PATH}"
        )

    metadata = json.loads(
        MODEL_METADATA_PATH.read_text(
            encoding="utf-8",
        )
    )

    threshold = metadata.get(
        "classification_threshold"
    )

    if threshold is None:
        raise ValueError(
            "classification_threshold is missing from model metadata."
        )

    return float(threshold)


def calculate_test_metrics(
    y_true: pd.Series,
    predictions: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
) -> dict:
    """Calculate final classification metrics."""

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1],
    ).ravel()

    return {
        "threshold": threshold,
        "test_rows": int(len(y_true)),
        "actual_late_orders": int(y_true.sum()),
        "actual_late_rate": float(y_true.mean()),
        "predicted_late_orders": int(predictions.sum()),

        "accuracy": float(
            accuracy_score(
                y_true,
                predictions,
            )
        ),

        "precision": float(
            precision_score(
                y_true,
                predictions,
                zero_division=0,
            )
        ),

        "recall": float(
            recall_score(
                y_true,
                predictions,
                zero_division=0,
            )
        ),

        "f1_score": float(
            f1_score(
                y_true,
                predictions,
                zero_division=0,
            )
        ),

        "roc_auc": float(
            roc_auc_score(
                y_true,
                probabilities,
            )
        ),

        "pr_auc": float(
            average_precision_score(
                y_true,
                probabilities,
            )
        ),

        "true_negative": int(tn),
        "false_positive": int(fp),
        "false_negative": int(fn),
        "true_positive": int(tp),

        "classification_report": classification_report(
            y_true,
            predictions,
            labels=[0, 1],
            target_names=[
                "on_time",
                "late",
            ],
            output_dict=True,
            zero_division=0,
        ),
    }


def save_test_predictions(
    test_data: pd.DataFrame,
    predictions: np.ndarray,
    probabilities: np.ndarray,
) -> None:
    """Save order-level test predictions."""

    output_columns = [
        "order_id",
        "order_purchase_timestamp",
        CLASSIFICATION_TARGET,
    ]

    prediction_data = test_data[
        output_columns
    ].copy()

    prediction_data = prediction_data.rename(
        columns={
            CLASSIFICATION_TARGET:
                "actual_late_delivery",
        }
    )

    prediction_data[
        "predicted_late_probability"
    ] = probabilities

    prediction_data[
        "predicted_late_delivery"
    ] = predictions

    prediction_data.to_parquet(
        TEST_PREDICTIONS_PATH,
        index=False,
    )


def save_confusion_matrix_chart(
    metrics: dict,
) -> None:
    """Save the final test confusion matrix chart."""

    matrix = np.array(
        [
            [
                metrics["true_negative"],
                metrics["false_positive"],
            ],
            [
                metrics["false_negative"],
                metrics["true_positive"],
            ],
        ]
    )

    plt.figure(figsize=(7, 6))

    plt.imshow(matrix)

    plt.title("Test confusion matrix")
    plt.xlabel("Predicted class")
    plt.ylabel("Actual class")

    plt.xticks(
        [0, 1],
        ["On time", "Late"],
    )

    plt.yticks(
        [0, 1],
        ["On time", "Late"],
    )

    for row_index in range(2):
        for column_index in range(2):
            plt.text(
                column_index,
                row_index,
                f"{matrix[row_index, column_index]:,}",
                horizontalalignment="center",
                verticalalignment="center",
            )

    plt.tight_layout()

    plt.savefig(
        CONFUSION_MATRIX_PATH,
        dpi=150,
    )

    plt.close()


def save_precision_recall_chart(
    y_true: pd.Series,
    probabilities: np.ndarray,
) -> None:
    """Save the test precision-recall curve."""

    precision, recall, _ = precision_recall_curve(
        y_true,
        probabilities,
    )

    baseline = float(
        y_true.mean()
    )

    plt.figure(figsize=(8, 6))

    plt.plot(
        recall,
        precision,
        label="Model",
    )

    plt.axhline(
        y=baseline,
        linestyle="--",
        label=f"Dummy baseline = {baseline:.4f}",
    )

    plt.title("Test precision-recall curve")
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.legend()
    plt.tight_layout()

    plt.savefig(
        PR_CURVE_PATH,
        dpi=150,
    )

    plt.close()


def main() -> None:
    """Run final classification test evaluation."""

    print("=" * 100)
    print("FINAL CLASSIFICATION TEST EVALUATION")
    print("=" * 100)

    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    test_data = load_test_data()
    pipeline = load_model_pipeline()
    selected_threshold = load_selected_threshold()

    X_test = test_data[
        MODEL_FEATURES
    ]

    y_test = test_data[
        CLASSIFICATION_TARGET
    ]

    print(
        f"\nTest rows: "
        f"{len(X_test):,}"
    )

    print(
        f"Actual late orders: "
        f"{int(y_test.sum()):,}"
    )

    print(
        f"Actual late rate: "
        f"{100 * y_test.mean():.2f}%"
    )

    print(
        f"Selected threshold: "
        f"{selected_threshold:.2f}"
    )

    # The saved pipeline automatically:
    # 1. preprocesses the raw 47 features,
    # 2. transforms them into the learned feature structure,
    # 3. sends them to the trained classifier.
    test_probabilities = (
        pipeline.predict_proba(
            X_test
        )[:, 1]
    )

    test_predictions = (
        test_probabilities
        >= selected_threshold
    ).astype(int)

    metrics = calculate_test_metrics(
        y_true=y_test,
        predictions=test_predictions,
        probabilities=test_probabilities,
        threshold=selected_threshold,
    )

    TEST_METRICS_PATH.write_text(
        json.dumps(
            metrics,
            indent=2,
        ),
        encoding="utf-8",
    )

    save_test_predictions(
        test_data=test_data,
        predictions=test_predictions,
        probabilities=test_probabilities,
    )

    save_confusion_matrix_chart(
        metrics
    )

    save_precision_recall_chart(
        y_true=y_test,
        probabilities=test_probabilities,
    )

    print("\n" + "=" * 100)
    print("FINAL TEST METRICS")
    print("=" * 100)

    print(
        f"Accuracy:  "
        f"{metrics['accuracy']:.4f}"
    )

    print(
        f"Precision: "
        f"{metrics['precision']:.4f}"
    )

    print(
        f"Recall:    "
        f"{metrics['recall']:.4f}"
    )

    print(
        f"F1-score:  "
        f"{metrics['f1_score']:.4f}"
    )

    print(
        f"ROC-AUC:   "
        f"{metrics['roc_auc']:.4f}"
    )

    print(
        f"PR-AUC:    "
        f"{metrics['pr_auc']:.4f}"
    )

    print("\nConfusion matrix values:")

    print(
        f"True negative:  "
        f"{metrics['true_negative']:,}"
    )

    print(
        f"False positive: "
        f"{metrics['false_positive']:,}"
    )

    print(
        f"False negative: "
        f"{metrics['false_negative']:,}"
    )

    print(
        f"True positive:  "
        f"{metrics['true_positive']:,}"
    )

    print("\n" + "=" * 100)
    print("CLASSIFICATION TEST EVALUATION COMPLETED")
    print("=" * 100)

    print(
        "\nTest metrics saved to:\n"
        f"{TEST_METRICS_PATH}"
    )

    print(
        "\nOrder-level predictions saved to:\n"
        f"{TEST_PREDICTIONS_PATH}"
    )

    print(
        "\nConfusion matrix chart saved to:\n"
        f"{CONFUSION_MATRIX_PATH}"
    )

    print(
        "\nPrecision-recall chart saved to:\n"
        f"{PR_CURVE_PATH}"
    )


if __name__ == "__main__":
    main()