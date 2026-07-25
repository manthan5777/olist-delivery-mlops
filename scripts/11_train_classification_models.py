"""Train and compare classification models.

Flow:

Raw training features
    -> fitted preprocessing
    -> transformed training features
    -> classifier training

Raw validation features
    -> training-fitted preprocessing
    -> transformed validation features
    -> classifier prediction

The test dataset is not used in this script.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
)

from src.models.classification_models import (  # noqa: E402
    get_classification_models,
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

TRAIN_PATH = SPLIT_DIRECTORY / "train.parquet"
VALIDATION_PATH = SPLIT_DIRECTORY / "validation.parquet"

MODEL_DIRECTORY = (
    PROJECT_ROOT
    / "models"
    / "classification"
)

REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "reports"
    / "classification"
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
    / "best_classification_pipeline.joblib"
)

BEST_MODEL_METADATA_PATH = (
    MODEL_DIRECTORY
    / "best_classification_metadata.json"
)


def load_dataset(path: Path) -> pd.DataFrame:
    """Load one Parquet dataset."""

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset was not found: {path}"
        )

    return pd.read_parquet(path)


def create_model_pipeline(model) -> Pipeline:
    """Connect preprocessing and classification model."""

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


def evaluate_classifier(
    model_name: str,
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_validation: pd.DataFrame,
    y_validation: pd.Series,
) -> dict:
    """Train one pipeline and evaluate it on validation data."""

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

    validation_probabilities = pipeline.predict_proba(
        X_validation
    )[:, 1]

    prediction_seconds = (
        time.perf_counter()
        - prediction_start
    )

    tn, fp, fn, tp = confusion_matrix(
        y_validation,
        validation_predictions,
        labels=[0, 1],
    ).ravel()

    metrics = {
        "model_name": model_name,
        "accuracy": float(
            accuracy_score(
                y_validation,
                validation_predictions,
            )
        ),
        "precision": float(
            precision_score(
                y_validation,
                validation_predictions,
                zero_division=0,
            )
        ),
        "recall": float(
            recall_score(
                y_validation,
                validation_predictions,
                zero_division=0,
            )
        ),
        "f1_score": float(
            f1_score(
                y_validation,
                validation_predictions,
                zero_division=0,
            )
        ),
        "roc_auc": float(
            roc_auc_score(
                y_validation,
                validation_probabilities,
            )
        ),
        "pr_auc": float(
            average_precision_score(
                y_validation,
                validation_probabilities,
            )
        ),
        "true_negative": int(tn),
        "false_positive": int(fp),
        "false_negative": int(fn),
        "true_positive": int(tp),
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
        f"Accuracy:  {metrics['accuracy']:.4f}"
    )
    print(
        f"Precision: {metrics['precision']:.4f}"
    )
    print(
        f"Recall:    {metrics['recall']:.4f}"
    )
    print(
        f"F1-score:  {metrics['f1_score']:.4f}"
    )
    print(
        f"ROC-AUC:   {metrics['roc_auc']:.4f}"
    )
    print(
        f"PR-AUC:    {metrics['pr_auc']:.4f}"
    )

    print("\nConfusion matrix values:")
    print(f"True negative:  {tn:,}")
    print(f"False positive: {fp:,}")
    print(f"False negative: {fn:,}")
    print(f"True positive:  {tp:,}")

    print(
        f"\nTraining time:   "
        f"{training_seconds:.2f} seconds"
    )

    print(
        f"Prediction time: "
        f"{prediction_seconds:.4f} seconds"
    )

    return metrics


def save_results(
    results: list[dict],
) -> None:
    """Save model-comparison metrics."""

    REPORT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    results_dataframe = pd.DataFrame(
        results
    ).sort_values(
        by="pr_auc",
        ascending=False,
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
    print("VALIDATION MODEL COMPARISON")
    print("=" * 100)

    display_columns = [
        "model_name",
        "accuracy",
        "precision",
        "recall",
        "f1_score",
        "roc_auc",
        "pr_auc",
        "training_seconds",
    ]

    print(
        results_dataframe[
            display_columns
        ].to_string(
            index=False,
            formatters={
                "accuracy": "{:.4f}".format,
                "precision": "{:.4f}".format,
                "recall": "{:.4f}".format,
                "f1_score": "{:.4f}".format,
                "roc_auc": "{:.4f}".format,
                "pr_auc": "{:.4f}".format,
                "training_seconds": "{:.2f}".format,
            },
        )
    )


def save_best_model(
    best_model_name: str,
    best_pipeline: Pipeline,
    best_metrics: dict,
) -> None:
    """Save the best fitted preprocessing-plus-model pipeline."""

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
        "selection_metric": "validation_pr_auc",
        "classification_threshold": 0.5,
        "feature_count": len(MODEL_FEATURES),
        "target": CLASSIFICATION_TARGET,
        "validation_metrics": best_metrics,
        "model_path": str(BEST_MODEL_PATH),
    }

    BEST_MODEL_METADATA_PATH.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Train and compare classification pipelines."""

    print("=" * 100)
    print("CLASSIFICATION MODEL TRAINING")
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
        CLASSIFICATION_TARGET
    ]

    X_validation = validation_data[
        MODEL_FEATURES
    ]

    y_validation = validation_data[
        CLASSIFICATION_TARGET
    ]

    print(
        f"\nTraining rows:   {len(X_train):,}"
    )

    print(
        f"Validation rows: {len(X_validation):,}"
    )

    print(
        f"Input features:  {len(MODEL_FEATURES)}"
    )

    print(
        f"Training late-order rate: "
        f"{100 * y_train.mean():.2f}%"
    )

    print(
        f"Validation late-order rate: "
        f"{100 * y_validation.mean():.2f}%"
    )

    models = get_classification_models()

    results = []

    best_pipeline = None
    best_model_name = None
    best_metrics = None
    best_pr_auc = float("-inf")

    for model_name, model in models.items():
        pipeline = create_model_pipeline(
            model
        )

        metrics = evaluate_classifier(
            model_name=model_name,
            pipeline=pipeline,
            X_train=X_train,
            y_train=y_train,
            X_validation=X_validation,
            y_validation=y_validation,
        )

        results.append(metrics)

        if metrics["pr_auc"] > best_pr_auc:
            best_pr_auc = metrics["pr_auc"]
            best_pipeline = pipeline
            best_model_name = model_name
            best_metrics = metrics

    save_results(results)

    if (
        best_pipeline is None
        or best_model_name is None
        or best_metrics is None
    ):
        raise RuntimeError(
            "No classification model was selected."
        )

    save_best_model(
        best_model_name=best_model_name,
        best_pipeline=best_pipeline,
        best_metrics=best_metrics,
    )

    print("\n" + "=" * 100)
    print("CLASSIFICATION TRAINING COMPLETED")
    print("=" * 100)

    print(
        f"\nBest model: "
        f"{best_model_name}"
    )

    print(
        f"Best validation PR-AUC: "
        f"{best_pr_auc:.4f}"
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