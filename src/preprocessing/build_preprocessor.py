"""Build the reusable Scikit-Learn preprocessing pipeline.

The preprocessing pipeline handles:

1. Numerical features
   - Missing values are replaced with the training-data median.
   - Values are standardized.

2. Categorical features
   - Missing values are replaced with the most frequent category.
   - Categories are converted into one-hot encoded numerical columns.
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.features.feature_config import (
    CATEGORICAL_FEATURES,
    NUMERICAL_FEATURES,
)


def build_preprocessor() -> ColumnTransformer:
    """Create and return an unfitted preprocessing pipeline."""

    numerical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                ),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
        ]
    )

    categorical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="most_frequent",
                ),
            ),
            (
                "encoder",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numerical",
                numerical_pipeline,
                NUMERICAL_FEATURES,
            ),
            (
                "categorical",
                categorical_pipeline,
                CATEGORICAL_FEATURES,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )

    return preprocessor
