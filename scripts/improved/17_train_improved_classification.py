"""Train improved late-delivery classifiers using a chronological validation split.

The script reads only training and validation splits. Models are selected by
validation average precision (PR-AUC); a probability threshold is selected by
validation F1 after model selection for an explicit operating point.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
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
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CATEGORICAL_FEATURES,
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
    NUMERICAL_FEATURES,
)
from src.features.improved_feature_engineering import (  # noqa: E402
    DERIVED_CATEGORICAL_FEATURES,
    DERIVED_NUMERICAL_FEATURES,
    ImprovedFeatureEngineer,
)


SPLIT_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "splits"
TRAIN_PATH = SPLIT_DIRECTORY / "train.parquet"
VALIDATION_PATH = SPLIT_DIRECTORY / "validation.parquet"
BASELINE_METRICS_PATH = PROJECT_ROOT / "reports" / "classification" / "validation_metrics.json"

MODEL_DIRECTORY = PROJECT_ROOT / "models" / "improved"
REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "improved" / "classification"
PIPELINE_PATH = MODEL_DIRECTORY / "classification_pipeline.joblib"
METADATA_PATH = MODEL_DIRECTORY / "classification_metadata.json"
METRICS_PATH = REPORT_DIRECTORY / "validation_metrics.csv"
METRICS_JSON_PATH = REPORT_DIRECTORY / "validation_metrics.json"
THRESHOLD_METRICS_PATH = REPORT_DIRECTORY / "threshold_metrics.csv"
THRESHOLD_SELECTION_PATH = REPORT_DIRECTORY / "threshold_selection.json"
THRESHOLD_CHART_PATH = REPORT_DIRECTORY / "threshold_curve.png"
BASELINE_COMPARISON_PATH = REPORT_DIRECTORY / "baseline_comparison.json"


def build_preprocessor() -> ColumnTransformer:
    """Build preprocessing for the fixed expanded feature schema."""

    categorical_features = CATEGORICAL_FEATURES + DERIVED_CATEGORICAL_FEATURES
    numerical_features = NUMERICAL_FEATURES + DERIVED_NUMERICAL_FEATURES
    return ColumnTransformer(
        transformers=[
            (
                "numerical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numerical_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical_features,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )


def build_models(y_train: pd.Series) -> dict[str, object]:
    """Return one bounded configuration per required model family."""

    positive_count = int(y_train.sum())
    negative_count = int(len(y_train) - positive_count)
    scale_pos_weight = negative_count / positive_count
    return {
        "dummy_classifier": DummyClassifier(strategy="prior"),
        "logistic_regression": LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=2_000,
            random_state=42,
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            learning_rate=0.08,
            max_iter=220,
            max_leaf_nodes=31,
            min_samples_leaf=30,
            l2_regularization=1.0,
            early_stopping=False,
            class_weight="balanced",
            random_state=42,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=50,
            max_depth=12,
            min_samples_leaf=15,
            max_features=0.5,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=50,
            max_depth=14,
            min_samples_leaf=12,
            max_features=0.5,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        ),
        "xgboost": XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            n_estimators=180,
            learning_rate=0.06,
            max_depth=6,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=2.0,
            scale_pos_weight=scale_pos_weight,
            tree_method="hist",
            n_jobs=-1,
            random_state=42,
        ),
    }


def create_pipeline(model: object) -> Pipeline:
    """Connect raw-input feature engineering, preprocessing, and a classifier."""

    return Pipeline(
        steps=[
            ("feature_engineer", ImprovedFeatureEngineer()),
            ("preprocessor", build_preprocessor()),
            ("model", model),
        ]
    )


def calculate_metrics(
    model_name: str,
    y_true: pd.Series,
    probabilities: np.ndarray,
    threshold: float,
    training_seconds: float,
    inference_seconds: float,
) -> dict[str, float | int | str]:
    """Calculate ranking and operating-point metrics for one classifier."""

    predictions = (probabilities >= threshold).astype(int)
    true_negative, false_positive, false_negative, true_positive = confusion_matrix(
        y_true,
        predictions,
        labels=[0, 1],
    ).ravel()
    return {
        "model_name": model_name,
        "threshold": float(threshold),
        "positive_rate_pr_auc_baseline": float(y_true.mean()),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1_score": float(f1_score(y_true, predictions, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "true_negative": int(true_negative),
        "false_positive": int(false_positive),
        "false_negative": int(false_negative),
        "true_positive": int(true_positive),
        "training_seconds": float(training_seconds),
        "inference_seconds": float(inference_seconds),
        "inference_ms_per_order": float(inference_seconds * 1_000 / len(y_true)),
    }


def evaluate_models(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_validation: pd.DataFrame,
    y_validation: pd.Series,
) -> tuple[list[dict[str, float | int | str]], dict[str, Pipeline]]:
    """Fit each bounded candidate on train and evaluate the chronological validation split."""

    results: list[dict[str, float | int | str]] = []
    fitted_pipelines: dict[str, Pipeline] = {}
    for model_name, model in build_models(y_train).items():
        pipeline = create_pipeline(model)
        print(f"Training {model_name}...")
        training_start = time.perf_counter()
        pipeline.fit(X_train, y_train)
        training_seconds = time.perf_counter() - training_start

        prediction_start = time.perf_counter()
        probabilities = pipeline.predict_proba(X_validation)[:, 1]
        inference_seconds = time.perf_counter() - prediction_start
        results.append(
            calculate_metrics(
                model_name=model_name,
                y_true=y_validation,
                probabilities=probabilities,
                threshold=0.50,
                training_seconds=training_seconds,
                inference_seconds=inference_seconds,
            )
        )
        fitted_pipelines[model_name] = pipeline
    return results, fitted_pipelines


def build_threshold_table(y_true: pd.Series, probabilities: np.ndarray) -> pd.DataFrame:
    """Calculate validation-only operating metrics across candidate thresholds."""

    thresholds = np.round(np.arange(0.05, 0.951, 0.01), 2)
    rows = [
        calculate_metrics(
            model_name="selected_model",
            y_true=y_true,
            probabilities=probabilities,
            threshold=float(threshold),
            training_seconds=0.0,
            inference_seconds=0.0,
        )
        for threshold in thresholds
    ]
    return pd.DataFrame(rows)


def load_original_logistic_pr_auc() -> float | None:
    """Read the previous validation Logistic Regression result for comparison only."""

    if not BASELINE_METRICS_PATH.exists():
        return None
    metrics = json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))
    for row in metrics:
        if row.get("model_name") == "logistic_regression":
            return float(row["pr_auc"])
    return None


def save_threshold_chart(thresholds: pd.DataFrame) -> None:
    """Save the validation-only threshold operating curve."""

    plt.figure(figsize=(9, 5))
    for column, label in [
        ("precision", "Precision"),
        ("recall", "Recall"),
        ("f1_score", "F1"),
    ]:
        plt.plot(thresholds["threshold"], thresholds[column], label=label)
    plt.xlabel("Probability threshold")
    plt.ylabel("Metric")
    plt.title("Validation Threshold Metrics for Selected Classifier")
    plt.legend()
    plt.tight_layout()
    plt.savefig(THRESHOLD_CHART_PATH, dpi=140)
    plt.close()


def main() -> None:
    """Run controlled chronological validation without reading test data."""

    required_columns = MODEL_FEATURES + [CLASSIFICATION_TARGET, "order_purchase_timestamp"]
    train_data = pd.read_parquet(TRAIN_PATH, columns=required_columns)
    validation_data = pd.read_parquet(VALIDATION_PATH, columns=required_columns)
    train_end = train_data["order_purchase_timestamp"].max()
    validation_start = validation_data["order_purchase_timestamp"].min()
    if train_end > validation_start:
        raise ValueError("Training data overlaps the later validation time period.")

    X_train = train_data[MODEL_FEATURES]
    y_train = train_data[CLASSIFICATION_TARGET]
    X_validation = validation_data[MODEL_FEATURES]
    y_validation = validation_data[CLASSIFICATION_TARGET]

    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    results, fitted_pipelines = evaluate_models(X_train, y_train, X_validation, y_validation)
    metrics = pd.DataFrame(results).sort_values("pr_auc", ascending=False)
    metrics.to_csv(METRICS_PATH, index=False)
    METRICS_JSON_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    best_result = metrics.iloc[0]
    best_model_name = str(best_result["model_name"])
    best_pipeline = fitted_pipelines[best_model_name]
    best_probabilities = best_pipeline.predict_proba(X_validation)[:, 1]
    threshold_metrics = build_threshold_table(y_validation, best_probabilities)
    threshold_metrics.to_csv(THRESHOLD_METRICS_PATH, index=False)
    selected_threshold = threshold_metrics.sort_values(
        ["f1_score", "recall", "precision"],
        ascending=[False, False, False],
    ).iloc[0]
    default_threshold = threshold_metrics.loc[
        np.isclose(threshold_metrics["threshold"], 0.50)
    ].iloc[0]
    save_threshold_chart(threshold_metrics)

    selected_threshold_metrics = {
        key: (int(value) if key.startswith(("true_", "false_")) else float(value))
        for key, value in selected_threshold.to_dict().items()
        if key not in {"model_name"}
    }
    threshold_payload = {
        "selection_metric": "validation_f1_score",
        "selected_threshold": float(selected_threshold["threshold"]),
        "default_threshold_metrics": default_threshold.to_dict(),
        "selected_threshold_metrics": selected_threshold_metrics,
    }
    THRESHOLD_SELECTION_PATH.write_text(json.dumps(threshold_payload, indent=2), encoding="utf-8")

    original_logistic_pr_auc = load_original_logistic_pr_auc()
    improved_logistic_pr_auc = float(
        metrics.loc[metrics["model_name"] == "logistic_regression", "pr_auc"].iloc[0]
    )
    baseline_comparison = {
        "original_logistic_regression_validation_pr_auc": original_logistic_pr_auc,
        "improved_logistic_regression_validation_pr_auc": improved_logistic_pr_auc,
        "absolute_pr_auc_change": (
            improved_logistic_pr_auc - original_logistic_pr_auc
            if original_logistic_pr_auc is not None
            else None
        ),
        "selected_model": best_model_name,
        "selected_model_validation_pr_auc": float(best_result["pr_auc"]),
    }
    BASELINE_COMPARISON_PATH.write_text(json.dumps(baseline_comparison, indent=2), encoding="utf-8")

    metadata = {
        "model_name": best_model_name,
        "selection_metric": "validation_pr_auc",
        "validation_strategy": "fixed_chronological_holdout",
        "candidate_configurations_per_family": 1,
        "classification_threshold": float(selected_threshold["threshold"]),
        "threshold_selection_metric": "validation_f1_score",
        "raw_feature_count": len(MODEL_FEATURES),
        "engineered_feature_count": len(MODEL_FEATURES) + len(DERIVED_CATEGORICAL_FEATURES) + len(DERIVED_NUMERICAL_FEATURES),
        "target": CLASSIFICATION_TARGET,
        "test_data_loaded": False,
        "validation_metrics_at_default_threshold": best_result.to_dict(),
        "threshold_validation_metrics": selected_threshold_metrics,
    }
    joblib.dump(best_pipeline, PIPELINE_PATH)
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\nValidation model comparison (sorted by PR-AUC):")
    print(metrics[["model_name", "pr_auc", "roc_auc", "precision", "recall", "f1_score", "accuracy", "training_seconds", "inference_ms_per_order"]].to_string(index=False))
    print(f"\nSelected model: {best_model_name}")
    print(f"Selected validation PR-AUC: {best_result['pr_auc']:.6f}")
    print(f"Validation F1 threshold: {selected_threshold['threshold']:.2f}")
    print("Test data was not loaded or evaluated.")


if __name__ == "__main__":
    main()