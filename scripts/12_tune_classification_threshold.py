"""Tune the classification probability threshold.

This script:

1. Loads the fitted classification pipeline.
2. Generates late-delivery probabilities for validation data.
3. Tests multiple probability thresholds.
4. Calculates precision, recall and F1-score at each threshold.
5. Selects the threshold with the highest validation F1-score.
6. Saves the selected threshold for later API predictions.

The test dataset is not used.
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
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
)


VALIDATION_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
    / "validation.parquet"
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

THRESHOLD_METRICS_PATH = (
    REPORT_DIRECTORY
    / "threshold_metrics.csv"
)

THRESHOLD_SELECTION_PATH = (
    REPORT_DIRECTORY
    / "threshold_selection.json"
)

THRESHOLD_CHART_PATH = (
    REPORT_DIRECTORY
    / "threshold_curve.png"
)


def load_validation_data() -> pd.DataFrame:
    """Load validation data."""

    if not VALIDATION_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Validation data not found: "
            f"{VALIDATION_DATA_PATH}"
        )

    return pd.read_parquet(
        VALIDATION_DATA_PATH
    )


def load_model_pipeline():
    """Load the fitted preprocessing-plus-model pipeline."""

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Classification pipeline not found: "
            f"{MODEL_PATH}"
        )

    return joblib.load(MODEL_PATH)


def calculate_threshold_metrics(
    y_true: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
) -> dict:
    """Calculate classification metrics at one threshold."""

    predictions = (
        probabilities >= threshold
    ).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1],
    ).ravel()

    return {
        "threshold": float(threshold),
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
        "true_negative": int(tn),
        "false_positive": int(fp),
        "false_negative": int(fn),
        "true_positive": int(tp),
        "predicted_late_count": int(
            predictions.sum()
        ),
    }


def create_threshold_table(
    y_true: pd.Series,
    probabilities: np.ndarray,
) -> pd.DataFrame:
    """Evaluate thresholds from 0.05 through 0.95."""

    thresholds = np.arange(
        0.05,
        0.951,
        0.01,
    )

    results = [
        calculate_threshold_metrics(
            y_true=y_true,
            probabilities=probabilities,
            threshold=round(
                float(threshold),
                2,
            ),
        )
        for threshold in thresholds
    ]

    return pd.DataFrame(results)


def select_best_threshold(
    threshold_table: pd.DataFrame,
) -> pd.Series:
    """Select the threshold with the highest F1-score."""

    ranked_table = threshold_table.sort_values(
        by=[
            "f1_score",
            "recall",
            "precision",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    )

    return ranked_table.iloc[0]


def save_threshold_chart(
    threshold_table: pd.DataFrame,
) -> None:
    """Save precision, recall and F1 by threshold."""

    plt.figure(figsize=(10, 6))

    plt.plot(
        threshold_table["threshold"],
        threshold_table["precision"],
        label="Precision",
    )

    plt.plot(
        threshold_table["threshold"],
        threshold_table["recall"],
        label="Recall",
    )

    plt.plot(
        threshold_table["threshold"],
        threshold_table["f1_score"],
        label="F1-score",
    )

    plt.axvline(
        x=0.50,
        linestyle="--",
        label="Default threshold 0.50",
    )

    plt.xlabel("Probability threshold")
    plt.ylabel("Metric value")
    plt.title(
        "Validation precision, recall and F1 by threshold"
    )
    plt.legend()
    plt.tight_layout()

    plt.savefig(
        THRESHOLD_CHART_PATH,
        dpi=150,
    )

    plt.close()


def update_model_metadata(
    selected_threshold: float,
    selected_metrics: dict,
) -> None:
    """Save the selected threshold with model metadata."""

    if MODEL_METADATA_PATH.exists():
        metadata = json.loads(
            MODEL_METADATA_PATH.read_text(
                encoding="utf-8",
            )
        )
    else:
        metadata = {}

    metadata[
        "classification_threshold"
    ] = selected_threshold

    metadata[
        "threshold_selection_metric"
    ] = "validation_f1_score"

    metadata[
        "threshold_validation_metrics"
    ] = selected_metrics

    MODEL_METADATA_PATH.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Run validation threshold tuning."""

    print("=" * 100)
    print("CLASSIFICATION THRESHOLD TUNING")
    print("=" * 100)

    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    validation_data = load_validation_data()
    pipeline = load_model_pipeline()

    X_validation = validation_data[
        MODEL_FEATURES
    ]

    y_validation = validation_data[
        CLASSIFICATION_TARGET
    ]

    print(
        f"\nValidation rows: "
        f"{len(X_validation):,}"
    )

    print(
        f"Actual late orders: "
        f"{int(y_validation.sum()):,}"
    )

    late_probabilities = (
        pipeline.predict_proba(
            X_validation
        )[:, 1]
    )

    threshold_table = create_threshold_table(
        y_true=y_validation,
        probabilities=late_probabilities,
    )

    selected_row = select_best_threshold(
        threshold_table
    )

    default_row = threshold_table.loc[
        np.isclose(
            threshold_table["threshold"],
            0.50,
        )
    ].iloc[0]

    selected_threshold = float(
        selected_row["threshold"]
    )

    selected_metrics = {
        key: (
            int(value)
            if key in {
                "true_negative",
                "false_positive",
                "false_negative",
                "true_positive",
                "predicted_late_count",
            }
            else float(value)
        )
        for key, value in selected_row.to_dict().items()
    }

    threshold_table.to_csv(
        THRESHOLD_METRICS_PATH,
        index=False,
    )

    THRESHOLD_SELECTION_PATH.write_text(
        json.dumps(
            {
                "selection_metric":
                    "validation_f1_score",
                "default_threshold_metrics":
                    default_row.to_dict(),
                "selected_threshold":
                    selected_threshold,
                "selected_threshold_metrics":
                    selected_metrics,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    save_threshold_chart(
        threshold_table
    )

    update_model_metadata(
        selected_threshold=selected_threshold,
        selected_metrics=selected_metrics,
    )

    print("\n" + "=" * 100)
    print("DEFAULT THRESHOLD: 0.50")
    print("=" * 100)

    print(
        f"Precision: "
        f"{default_row['precision']:.4f}"
    )

    print(
        f"Recall:    "
        f"{default_row['recall']:.4f}"
    )

    print(
        f"F1-score:  "
        f"{default_row['f1_score']:.4f}"
    )

    print("\n" + "=" * 100)
    print(
        f"SELECTED THRESHOLD: "
        f"{selected_threshold:.2f}"
    )
    print("=" * 100)

    print(
        f"Precision: "
        f"{selected_row['precision']:.4f}"
    )

    print(
        f"Recall:    "
        f"{selected_row['recall']:.4f}"
    )

    print(
        f"F1-score:  "
        f"{selected_row['f1_score']:.4f}"
    )

    print("\nConfusion matrix values:")

    print(
        f"True negative:  "
        f"{int(selected_row['true_negative']):,}"
    )

    print(
        f"False positive: "
        f"{int(selected_row['false_positive']):,}"
    )

    print(
        f"False negative: "
        f"{int(selected_row['false_negative']):,}"
    )

    print(
        f"True positive:  "
        f"{int(selected_row['true_positive']):,}"
    )

    print("\n" + "=" * 100)
    print("THRESHOLD TUNING COMPLETED")
    print("=" * 100)

    print(
        "\nThreshold table saved to:\n"
        f"{THRESHOLD_METRICS_PATH}"
    )

    print(
        "\nThreshold chart saved to:\n"
        f"{THRESHOLD_CHART_PATH}"
    )

    print(
        "\nModel metadata updated at:\n"
        f"{MODEL_METADATA_PATH}"
    )

    print("\nThe test dataset was not used.")


if __name__ == "__main__":
    main()