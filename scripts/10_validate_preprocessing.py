"""Build, fit and validate the preprocessing pipeline.

This script:

1. Loads train, validation and test Parquet files.
2. Selects only approved model features.
3. Fits preprocessing only on the training data.
4. Transforms train, validation and test data.
5. Confirms missing values were handled.
6. Confirms every split has the same transformed structure.
7. Displays the newly generated feature names.
8. Saves a preprocessing report for reproducibility.

This script does not train a machine-learning model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Make the src package importable when this script is executed
# directly from the project root.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    NUMERICAL_FEATURES,
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

REPORT_PATH = (
    PROJECT_ROOT
    / "reports"
    / "preprocessing_report.json"
)


SPLIT_FILES = {
    "train": "train.parquet",
    "validation": "validation.parquet",
    "test": "test.parquet",
}


def load_split(
    split_name: str,
    filename: str,
) -> pd.DataFrame:
    """Load one Parquet data split."""

    file_path = SPLIT_DIRECTORY / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"{split_name} file was not found: {file_path}"
        )

    dataframe = pd.read_parquet(file_path)

    missing_model_columns = sorted(
        set(MODEL_FEATURES)
        - set(dataframe.columns)
    )

    if missing_model_columns:
        raise ValueError(
            f"{split_name} is missing model features: "
            f"{missing_model_columns}"
        )

    return dataframe


def count_missing_values(
    dataframe: pd.DataFrame,
) -> int:
    """Count missing values in approved model features."""

    return int(
        dataframe[MODEL_FEATURES]
        .isna()
        .sum()
        .sum()
    )


def get_missing_value_columns(
    dataframe: pd.DataFrame,
) -> dict[str, int]:
    """Return columns containing missing model-feature values."""

    missing_counts = (
        dataframe[MODEL_FEATURES]
        .isna()
        .sum()
    )

    missing_counts = missing_counts[
        missing_counts > 0
    ]

    return {
        column: int(count)
        for column, count
        in missing_counts.items()
    }


def validate_transformed_data(
    split_name: str,
    original_dataframe: pd.DataFrame,
    transformed_array: np.ndarray,
    expected_feature_count: int,
) -> None:
    """Validate one transformed data split."""

    if transformed_array.shape[0] != len(
        original_dataframe
    ):
        raise ValueError(
            f"{split_name}: transformed row count changed."
        )

    if transformed_array.shape[1] != expected_feature_count:
        raise ValueError(
            f"{split_name}: transformed feature count differs "
            "from the training feature count."
        )

    if not np.isfinite(transformed_array).all():
        invalid_value_count = int(
            (~np.isfinite(transformed_array)).sum()
        )

        raise ValueError(
            f"{split_name}: transformed data contains "
            f"{invalid_value_count:,} NaN or infinite values."
        )


def get_learned_numerical_medians(
    preprocessor,
) -> dict[str, float]:
    """Extract median values learned from the training data."""

    numerical_pipeline = (
        preprocessor
        .named_transformers_["numerical"]
    )

    numerical_imputer = (
        numerical_pipeline
        .named_steps["imputer"]
    )

    learned_medians = {
        feature_name: float(median_value)
        for feature_name, median_value
        in zip(
            NUMERICAL_FEATURES,
            numerical_imputer.statistics_,
            strict=True,
        )
    }

    return learned_medians


def get_learned_category_counts(
    preprocessor,
) -> dict[str, int]:
    """Count categories learned for every categorical feature."""

    categorical_pipeline = (
        preprocessor
        .named_transformers_["categorical"]
    )

    encoder = (
        categorical_pipeline
        .named_steps["encoder"]
    )

    category_counts = {
        feature_name: int(len(categories))
        for feature_name, categories
        in zip(
            CATEGORICAL_FEATURES,
            encoder.categories_,
            strict=True,
        )
    }

    return category_counts


def save_report(
    report: dict,
) -> None:
    """Save preprocessing information as JSON."""

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Run preprocessing validation."""

    print("=" * 100)
    print("PREPROCESSING PIPELINE VALIDATION")
    print("=" * 100)

    datasets = {
        split_name: load_split(
            split_name,
            filename,
        )
        for split_name, filename
        in SPLIT_FILES.items()
    }

    # Select only the 47 approved input features.
    X_train = datasets["train"][MODEL_FEATURES]
    X_validation = datasets["validation"][MODEL_FEATURES]
    X_test = datasets["test"][MODEL_FEATURES]

    print("\nRaw input information:")
    print(
        f"Categorical features: "
        f"{len(CATEGORICAL_FEATURES)}"
    )
    print(
        f"Numerical features:   "
        f"{len(NUMERICAL_FEATURES)}"
    )
    print(
        f"Total raw features:   "
        f"{len(MODEL_FEATURES)}"
    )

    print("\nMissing values before preprocessing:")

    for split_name, dataframe in datasets.items():
        missing_count = count_missing_values(
            dataframe
        )

        print(
            f"{split_name:<12} "
            f"{missing_count:>8,}"
        )

    # Create an unfitted preprocessor.
    preprocessor = build_preprocessor()

    print("\nFitting preprocessing on training data only...")

    # fit_transform does two things:
    # 1. Learns medians, means, standard deviations and categories.
    # 2. Transforms the training data.
    X_train_transformed = (
        preprocessor.fit_transform(X_train)
    )

    # Validation and test data must not teach the preprocessor
    # anything. We only apply the rules learned from training.
    X_validation_transformed = (
        preprocessor.transform(X_validation)
    )

    X_test_transformed = (
        preprocessor.transform(X_test)
    )

    transformed_feature_names = (
        preprocessor
        .get_feature_names_out()
        .tolist()
    )

    transformed_feature_count = len(
        transformed_feature_names
    )

    validate_transformed_data(
        split_name="train",
        original_dataframe=datasets["train"],
        transformed_array=X_train_transformed,
        expected_feature_count=transformed_feature_count,
    )

    validate_transformed_data(
        split_name="validation",
        original_dataframe=datasets["validation"],
        transformed_array=X_validation_transformed,
        expected_feature_count=transformed_feature_count,
    )

    validate_transformed_data(
        split_name="test",
        original_dataframe=datasets["test"],
        transformed_array=X_test_transformed,
        expected_feature_count=transformed_feature_count,
    )

    learned_medians = get_learned_numerical_medians(
        preprocessor
    )

    learned_category_counts = (
        get_learned_category_counts(
            preprocessor
        )
    )

    print("\n" + "=" * 100)
    print("TRANSFORMED DATA SHAPES")
    print("=" * 100)

    print(
        f"Train:      "
        f"{X_train_transformed.shape}"
    )

    print(
        f"Validation: "
        f"{X_validation_transformed.shape}"
    )

    print(
        f"Test:       "
        f"{X_test_transformed.shape}"
    )

    print(
        f"\nRaw feature count:         "
        f"{len(MODEL_FEATURES)}"
    )

    print(
        f"Transformed feature count: "
        f"{transformed_feature_count}"
    )

    print("\nMissing or infinite values after preprocessing:")

    print(
        "Train:      "
        f"{int((~np.isfinite(X_train_transformed)).sum()):,}"
    )

    print(
        "Validation: "
        f"{int((~np.isfinite(X_validation_transformed)).sum()):,}"
    )

    print(
        "Test:       "
        f"{int((~np.isfinite(X_test_transformed)).sum()):,}"
    )

    print("\n" + "=" * 100)
    print("CATEGORIES LEARNED FROM TRAINING DATA")
    print("=" * 100)

    for feature_name, category_count in (
        learned_category_counts.items()
    ):
        print(
            f"{feature_name:<30} "
            f"{category_count:>4} categories"
        )

    print("\n" + "=" * 100)
    print("FIRST 30 TRANSFORMED FEATURE NAMES")
    print("=" * 100)

    for feature_name in transformed_feature_names[:30]:
        print(f"  {feature_name}")

    report = {
        "raw_feature_count": len(
            MODEL_FEATURES
        ),
        "categorical_feature_count": len(
            CATEGORICAL_FEATURES
        ),
        "numerical_feature_count": len(
            NUMERICAL_FEATURES
        ),
        "transformed_feature_count":
            transformed_feature_count,
        "input_shapes": {
            "train": list(X_train.shape),
            "validation": list(
                X_validation.shape
            ),
            "test": list(X_test.shape),
        },
        "transformed_shapes": {
            "train": list(
                X_train_transformed.shape
            ),
            "validation": list(
                X_validation_transformed.shape
            ),
            "test": list(
                X_test_transformed.shape
            ),
        },
        "missing_values_before": {
            split_name: count_missing_values(
                dataframe
            )
            for split_name, dataframe
            in datasets.items()
        },
        "columns_with_missing_values": {
            split_name: get_missing_value_columns(
                dataframe
            )
            for split_name, dataframe
            in datasets.items()
        },
        "invalid_values_after": {
            "train": int(
                (
                    ~np.isfinite(
                        X_train_transformed
                    )
                ).sum()
            ),
            "validation": int(
                (
                    ~np.isfinite(
                        X_validation_transformed
                    )
                ).sum()
            ),
            "test": int(
                (
                    ~np.isfinite(
                        X_test_transformed
                    )
                ).sum()
            ),
        },
        "learned_numerical_medians":
            learned_medians,
        "learned_category_counts":
            learned_category_counts,
        "transformed_feature_names":
            transformed_feature_names,
    }

    save_report(report)

    print("\n" + "=" * 100)
    print("PREPROCESSING VALIDATION COMPLETED")
    print("=" * 100)

    print("\nTraining-only fit:               PASSED")
    print("Row-count validation:            PASSED")
    print("Feature-count consistency:       PASSED")
    print("Missing-value handling:          PASSED")
    print("Infinite-value validation:       PASSED")
    print("Unknown-category protection:     ENABLED")

    print(
        "\nPreprocessing report saved to:\n"
        f"{REPORT_PATH}"
    )


if __name__ == "__main__":
    main()