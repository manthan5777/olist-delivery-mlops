"""Validate the improved feature transformer and preprocessing without test data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import MODEL_FEATURES  # noqa: E402
from src.features.improved_feature_engineering import (  # noqa: E402
    ImprovedFeatureEngineer,
    get_improved_feature_roles,
)


SPLIT_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "splits"
REPORT_PATH = PROJECT_ROOT / "reports" / "improved" / "preprocessing_validation.json"


def build_preprocessor(
    categorical_features: list[str],
    numerical_features: list[str],
) -> ColumnTransformer:
    """Build preprocessing for the expanded feature schema."""

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
    )


def main() -> None:
    """Fit only on train and validate feature and preprocessing invariants."""

    train_data = pd.read_parquet(SPLIT_DIRECTORY / "train.parquet", columns=MODEL_FEATURES)
    validation_data = pd.read_parquet(
        SPLIT_DIRECTORY / "validation.parquet",
        columns=MODEL_FEATURES,
    )
    engineer = ImprovedFeatureEngineer()
    train_features = engineer.fit_transform(train_data)
    validation_features = engineer.transform(validation_data)

    if list(train_features.columns) != list(validation_features.columns):
        raise ValueError("Train and validation engineered feature schemas differ.")

    categorical, numerical = get_improved_feature_roles(train_features.columns)
    preprocessor = build_preprocessor(categorical, numerical)
    train_processed = preprocessor.fit_transform(train_features)
    validation_processed = preprocessor.transform(validation_features)

    if not np.isfinite(train_processed).all() or not np.isfinite(validation_processed).all():
        raise ValueError("Preprocessed features contain NaN or infinite values.")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "raw_feature_count": len(MODEL_FEATURES),
        "engineered_feature_count": int(train_features.shape[1]),
        "derived_feature_count": int(train_features.shape[1] - len(MODEL_FEATURES)),
        "categorical_feature_count": len(categorical),
        "numerical_feature_count": len(numerical),
        "train_preprocessed_shape": list(train_processed.shape),
        "validation_preprocessed_shape": list(validation_processed.shape),
        "train_invalid_values": int((~np.isfinite(train_processed)).sum()),
        "validation_invalid_values": int((~np.isfinite(validation_processed)).sum()),
        "test_data_loaded": False,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print("Improved preprocessing validation: PASSED")


if __name__ == "__main__":
    main()