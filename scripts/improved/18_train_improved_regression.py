"""Train improved delivery-duration regressors with chronological validation.

Only train and validation data are read. A candidate must beat the validation
dummy MAE before it can be selected as the saved improved model.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from xgboost import XGBRegressor


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    NUMERICAL_FEATURES,
    REGRESSION_TARGET,
)
from src.features.improved_feature_engineering import (  # noqa: E402
    DERIVED_CATEGORICAL_FEATURES,
    DERIVED_NUMERICAL_FEATURES,
    ImprovedFeatureEngineer,
)


SPLIT_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "splits"
TRAIN_PATH = SPLIT_DIRECTORY / "train.parquet"
VALIDATION_PATH = SPLIT_DIRECTORY / "validation.parquet"
BASELINE_METRICS_PATH = PROJECT_ROOT / "reports" / "regression" / "validation_metrics.json"

MODEL_DIRECTORY = PROJECT_ROOT / "models" / "improved"
REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "improved" / "regression"
PIPELINE_PATH = MODEL_DIRECTORY / "regression_pipeline.joblib"
METADATA_PATH = MODEL_DIRECTORY / "regression_metadata.json"
METRICS_PATH = REPORT_DIRECTORY / "validation_metrics.csv"
METRICS_JSON_PATH = REPORT_DIRECTORY / "validation_metrics.json"
BASELINE_COMPARISON_PATH = REPORT_DIRECTORY / "baseline_comparison.json"


def build_preprocessor() -> ColumnTransformer:
    """Build preprocessing for raw plus internally engineered features."""

    return ColumnTransformer(
        transformers=[
            (
                "numerical",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]),
                NUMERICAL_FEATURES + DERIVED_NUMERICAL_FEATURES,
            ),
            (
                "categorical",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                ]),
                CATEGORICAL_FEATURES + DERIVED_CATEGORICAL_FEATURES,
            ),
        ],
        remainder="drop",
    )


def build_models() -> dict[str, object]:
    """Return one conservative candidate configuration per requested family."""

    log_target_ridge = TransformedTargetRegressor(
        regressor=Ridge(alpha=10.0),
        transformer=FunctionTransformer(np.log1p, inverse_func=np.expm1, validate=False),
    )
    return {
        "dummy_regressor": DummyRegressor(strategy="median"),
        "ridge": Ridge(alpha=10.0),
        "ridge_log_target": log_target_ridge,
        "elastic_net": ElasticNet(alpha=0.03, l1_ratio=0.2, max_iter=5_000, random_state=42),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            learning_rate=0.06,
            max_iter=180,
            max_leaf_nodes=31,
            min_samples_leaf=30,
            l2_regularization=2.0,
            early_stopping=False,
            random_state=42,
        ),
        "random_forest": RandomForestRegressor(
            n_estimators=40,
            max_depth=12,
            min_samples_leaf=15,
            max_features=0.5,
            n_jobs=-1,
            random_state=42,
        ),
        "extra_trees": ExtraTreesRegressor(
            n_estimators=40,
            max_depth=14,
            min_samples_leaf=12,
            max_features=0.5,
            n_jobs=-1,
            random_state=42,
        ),
        "xgboost": XGBRegressor(
            objective="reg:squarederror",
            n_estimators=180,
            learning_rate=0.06,
            max_depth=6,
            min_child_weight=8,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=3.0,
            tree_method="hist",
            n_jobs=-1,
            random_state=42,
        ),
    }


def create_pipeline(model: object) -> Pipeline:
    """Connect raw input engineering, preprocessing, and a regressor."""

    return Pipeline([
        ("feature_engineer", ImprovedFeatureEngineer()),
        ("preprocessor", build_preprocessor()),
        ("model", model),
    ])


def evaluate(
    model_name: str,
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_validation: pd.DataFrame,
    y_validation: pd.Series,
) -> tuple[dict[str, float | str], Pipeline]:
    """Fit one candidate on train and measure it on later validation records."""

    print(f"Training {model_name}...")
    train_start = time.perf_counter()
    pipeline.fit(X_train, y_train)
    training_seconds = time.perf_counter() - train_start
    inference_start = time.perf_counter()
    predictions = pipeline.predict(X_validation)
    inference_seconds = time.perf_counter() - inference_start
    absolute_error = np.abs(y_validation.to_numpy() - predictions)
    metrics = {
        "model_name": model_name,
        "mae": float(mean_absolute_error(y_validation, predictions)),
        "rmse": float(np.sqrt(mean_squared_error(y_validation, predictions))),
        "median_absolute_error": float(median_absolute_error(y_validation, predictions)),
        "r2_score": float(r2_score(y_validation, predictions)),
        "within_2_days": float(np.mean(absolute_error <= 2.0)),
        "within_5_days": float(np.mean(absolute_error <= 5.0)),
        "within_7_days": float(np.mean(absolute_error <= 7.0)),
        "training_seconds": float(training_seconds),
        "inference_seconds": float(inference_seconds),
        "inference_ms_per_order": float(inference_seconds * 1_000 / len(y_validation)),
    }
    return metrics, pipeline


def original_dummy_mae() -> float | None:
    """Load the existing dummy baseline metric for transparent comparison."""

    if not BASELINE_METRICS_PATH.exists():
        return None
    rows = json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))
    for row in rows:
        if row.get("model_name") == "dummy_regressor":
            return float(row["mae"])
    return None


def main() -> None:
    """Compare bounded regressors without accessing the test split."""

    columns = MODEL_FEATURES + [REGRESSION_TARGET, "order_purchase_timestamp"]
    train_data = pd.read_parquet(TRAIN_PATH, columns=columns)
    validation_data = pd.read_parquet(VALIDATION_PATH, columns=columns)
    if train_data["order_purchase_timestamp"].max() > validation_data["order_purchase_timestamp"].min():
        raise ValueError("Training data overlaps the later validation time period.")

    X_train = train_data[MODEL_FEATURES]
    y_train = train_data[REGRESSION_TARGET]
    X_validation = validation_data[MODEL_FEATURES]
    y_validation = validation_data[REGRESSION_TARGET]
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, float | str]] = []
    pipelines: dict[str, Pipeline] = {}
    for model_name, model in build_models().items():
        metrics, pipeline = evaluate(
            model_name,
            create_pipeline(model),
            X_train,
            y_train,
            X_validation,
            y_validation,
        )
        results.append(metrics)
        pipelines[model_name] = pipeline

    metrics_frame = pd.DataFrame(results).sort_values("mae")
    metrics_frame.to_csv(METRICS_PATH, index=False)
    METRICS_JSON_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    dummy_result = metrics_frame.loc[metrics_frame["model_name"] == "dummy_regressor"].iloc[0]
    best_result = metrics_frame.iloc[0]
    dummy_mae = float(dummy_result["mae"])
    best_mae = float(best_result["mae"])
    selected_model_name = str(best_result["model_name"])
    improvement_percent = 100 * (dummy_mae - best_mae) / dummy_mae
    selected_beats_dummy = selected_model_name != "dummy_regressor" and best_mae < dummy_mae

    baseline_comparison = {
        "original_dummy_validation_mae": original_dummy_mae(),
        "improved_dummy_validation_mae": dummy_mae,
        "selected_model": selected_model_name,
        "selected_validation_mae": best_mae,
        "mae_improvement_vs_improved_dummy_percent": improvement_percent,
        "selected_model_beats_dummy": selected_beats_dummy,
    }
    BASELINE_COMPARISON_PATH.write_text(json.dumps(baseline_comparison, indent=2), encoding="utf-8")

    metadata = {
        "model_name": selected_model_name,
        "selection_metric": "validation_mae",
        "validation_strategy": "fixed_chronological_holdout",
        "candidate_configurations_per_family": 1,
        "raw_feature_count": len(MODEL_FEATURES),
        "engineered_feature_count": len(MODEL_FEATURES) + len(DERIVED_CATEGORICAL_FEATURES) + len(DERIVED_NUMERICAL_FEATURES),
        "target": REGRESSION_TARGET,
        "test_data_loaded": False,
        "selected_model_beats_dummy": selected_beats_dummy,
        "dummy_validation_mae": dummy_mae,
        "selected_validation_metrics": best_result.to_dict(),
    }
    if selected_beats_dummy:
        joblib.dump(pipelines[selected_model_name], PIPELINE_PATH)
        metadata["model_saved"] = True
        metadata["model_path"] = str(PIPELINE_PATH)
    else:
        metadata["model_saved"] = False
        metadata["reason"] = "No candidate beat the validation dummy MAE."
        if PIPELINE_PATH.exists():
            PIPELINE_PATH.unlink()
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print("\nValidation model comparison (sorted by MAE):")
    print(metrics_frame[["model_name", "mae", "rmse", "median_absolute_error", "r2_score", "within_2_days", "within_5_days", "within_7_days", "training_seconds", "inference_ms_per_order"]].to_string(index=False))
    print(f"\nSelected model: {selected_model_name}")
    print(f"Selected validation MAE: {best_mae:.6f}")
    print(f"Improvement vs dummy MAE: {improvement_percent:.2f}%")
    print(f"Saved pipeline: {selected_beats_dummy}")
    print("Test data was not loaded or evaluated.")


if __name__ == "__main__":
    main()