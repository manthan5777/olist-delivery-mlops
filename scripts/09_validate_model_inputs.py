"""Validate the feature configuration and prepared data splits.

This script checks that:

1. Every selected model feature exists.
2. Targets are not accidentally included as features.
3. Tracking columns are not given to the model.
4. Future-information columns are excluded.
5. Numerical features have numerical data types.
6. Order IDs are unique within each split.
7. Classification targets contain only 0 and 1.
8. Regression targets are present and non-negative.
9. Train, validation and test datasets follow the same schema.
10. A feature manifest is saved for reproducibility.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


# -------------------------------------------------------------------
# Project paths
# -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Add the project root to Python's module search path.
# This allows the script to import code from src/.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    ANALYSIS_ONLY_COLUMNS,
    CATEGORICAL_FEATURES,
    CLASSIFICATION_TARGET,
    FORBIDDEN_MODEL_COLUMNS,
    MODEL_FEATURES,
    NUMERICAL_FEATURES,
    REGRESSION_TARGET,
    TRACKING_COLUMNS,
)


SPLIT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
)

SPLIT_FILES = {
    "train": "train.parquet",
    "validation": "validation.parquet",
    "test": "test.parquet",
}

FEATURE_MANIFEST_PATH = (
    PROJECT_ROOT
    / "reports"
    / "feature_manifest.json"
)


def load_split(
    split_name: str,
    filename: str,
) -> pd.DataFrame:
    """Load one prepared Parquet split."""

    file_path = SPLIT_DIRECTORY / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"{split_name} split was not found: {file_path}"
        )

    dataframe = pd.read_parquet(file_path)

    return dataframe


def find_duplicates(values: list[str]) -> list[str]:
    """Return duplicated strings from a list."""

    seen = set()
    duplicates = set()

    for value in values:
        if value in seen:
            duplicates.add(value)

        seen.add(value)

    return sorted(duplicates)


def validate_feature_configuration() -> None:
    """Validate the feature lists before checking the datasets."""

    print("\n" + "=" * 100)
    print("1. FEATURE CONFIGURATION VALIDATION")
    print("=" * 100)

    categorical_duplicates = find_duplicates(
        CATEGORICAL_FEATURES
    )

    numerical_duplicates = find_duplicates(
        NUMERICAL_FEATURES
    )

    all_feature_duplicates = find_duplicates(
        MODEL_FEATURES
    )

    if categorical_duplicates:
        raise ValueError(
            "Duplicate categorical features found: "
            f"{categorical_duplicates}"
        )

    if numerical_duplicates:
        raise ValueError(
            "Duplicate numerical features found: "
            f"{numerical_duplicates}"
        )

    if all_feature_duplicates:
        raise ValueError(
            "Duplicate model features found: "
            f"{all_feature_duplicates}"
        )

    categorical_numerical_overlap = sorted(
        set(CATEGORICAL_FEATURES).intersection(
            NUMERICAL_FEATURES
        )
    )

    if categorical_numerical_overlap:
        raise ValueError(
            "Some columns appear as both categorical and numerical: "
            f"{categorical_numerical_overlap}"
        )

    leakage_columns = sorted(
        set(MODEL_FEATURES).intersection(
            FORBIDDEN_MODEL_COLUMNS
        )
    )

    if leakage_columns:
        raise ValueError(
            "Forbidden columns were included as model inputs: "
            f"{leakage_columns}"
        )

    print(
        f"Categorical feature count: "
        f"{len(CATEGORICAL_FEATURES)}"
    )

    print(
        f"Numerical feature count:   "
        f"{len(NUMERICAL_FEATURES)}"
    )

    print(
        f"Total model features:      "
        f"{len(MODEL_FEATURES)}"
    )

    print("\nTargets excluded from features: PASSED")
    print("Tracking columns excluded:      PASSED")
    print("Future columns excluded:        PASSED")
    print("Duplicate feature check:        PASSED")
    print("Feature-group overlap check:    PASSED")


def validate_required_columns(
    dataframe: pd.DataFrame,
    split_name: str,
) -> None:
    """Confirm that all required columns exist in a split."""

    required_columns = set(
        MODEL_FEATURES
        + TRACKING_COLUMNS
        + ANALYSIS_ONLY_COLUMNS
        + [
            CLASSIFICATION_TARGET,
            REGRESSION_TARGET,
        ]
    )

    available_columns = set(dataframe.columns)

    missing_columns = sorted(
        required_columns - available_columns
    )

    if missing_columns:
        raise ValueError(
            f"{split_name} is missing required columns: "
            f"{missing_columns}"
        )


def validate_unique_orders(
    dataframe: pd.DataFrame,
    split_name: str,
) -> None:
    """Confirm that each order appears once in a split."""

    duplicate_order_count = dataframe.duplicated(
        subset=["order_id"],
        keep=False,
    ).sum()

    if duplicate_order_count != 0:
        raise ValueError(
            f"{split_name} contains "
            f"{duplicate_order_count:,} duplicated order rows."
        )


def validate_classification_target(
    dataframe: pd.DataFrame,
    split_name: str,
) -> None:
    """Validate the binary classification target."""

    missing_target_count = dataframe[
        CLASSIFICATION_TARGET
    ].isna().sum()

    if missing_target_count != 0:
        raise ValueError(
            f"{split_name} contains "
            f"{missing_target_count:,} missing classification targets."
        )

    target_values = set(
        dataframe[
            CLASSIFICATION_TARGET
        ].dropna().unique().tolist()
    )

    expected_values = {0, 1}

    if not target_values.issubset(expected_values):
        raise ValueError(
            f"{split_name} contains unexpected classification "
            f"target values: {sorted(target_values)}"
        )


def validate_regression_target(
    dataframe: pd.DataFrame,
    split_name: str,
) -> None:
    """Validate the delivery-duration regression target."""

    missing_target_count = dataframe[
        REGRESSION_TARGET
    ].isna().sum()

    if missing_target_count != 0:
        raise ValueError(
            f"{split_name} contains "
            f"{missing_target_count:,} missing regression targets."
        )

    negative_target_count = (
        dataframe[REGRESSION_TARGET] < 0
    ).sum()

    if negative_target_count != 0:
        raise ValueError(
            f"{split_name} contains "
            f"{negative_target_count:,} negative delivery durations."
        )


def validate_numerical_feature_types(
    dataframe: pd.DataFrame,
    split_name: str,
) -> None:
    """Confirm that numerical features contain numerical data."""

    invalid_columns = []

    for column in NUMERICAL_FEATURES:
        if not pd.api.types.is_numeric_dtype(
            dataframe[column]
        ):
            invalid_columns.append(
                {
                    "column": column,
                    "dtype": str(dataframe[column].dtype),
                }
            )

    if invalid_columns:
        raise ValueError(
            f"{split_name} contains non-numerical data types "
            f"in numerical features: {invalid_columns}"
        )


def summarize_split(
    dataframe: pd.DataFrame,
    split_name: str,
) -> dict:
    """Create a summary of one data split."""

    classification_positive_count = int(
        dataframe[CLASSIFICATION_TARGET].sum()
    )

    classification_positive_rate = float(
        dataframe[CLASSIFICATION_TARGET].mean()
    )

    missing_feature_values = int(
        dataframe[MODEL_FEATURES]
        .isna()
        .sum()
        .sum()
    )

    features_with_missing_values = (
        dataframe[MODEL_FEATURES]
        .isna()
        .sum()
    )

    features_with_missing_values = (
        features_with_missing_values[
            features_with_missing_values > 0
        ]
        .index
        .tolist()
    )

    start_date = pd.to_datetime(
        dataframe["order_purchase_timestamp"]
    ).min()

    end_date = pd.to_datetime(
        dataframe["order_purchase_timestamp"]
    ).max()

    return {
        "split": split_name,
        "rows": int(len(dataframe)),
        "unique_orders": int(
            dataframe["order_id"].nunique()
        ),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "classification_positive_count":
            classification_positive_count,
        "classification_positive_rate":
            classification_positive_rate,
        "regression_target_mean": float(
            dataframe[REGRESSION_TARGET].mean()
        ),
        "regression_target_median": float(
            dataframe[REGRESSION_TARGET].median()
        ),
        "missing_feature_values":
            missing_feature_values,
        "features_with_missing_values":
            features_with_missing_values,
    }


def validate_schema_consistency(
    datasets: dict[str, pd.DataFrame],
) -> None:
    """Check that train, validation and test have the same columns."""

    train_columns = list(
        datasets["train"].columns
    )

    for split_name, dataframe in datasets.items():
        split_columns = list(dataframe.columns)

        if split_columns != train_columns:
            raise ValueError(
                f"{split_name} columns or column order differ "
                "from the training dataset."
            )


def save_feature_manifest(
    split_summaries: list[dict],
) -> None:
    """Save the approved feature contract as JSON."""

    FEATURE_MANIFEST_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "tracking_columns": TRACKING_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "numerical_features": NUMERICAL_FEATURES,
        "model_features": MODEL_FEATURES,
        "classification_target":
            CLASSIFICATION_TARGET,
        "regression_target":
            REGRESSION_TARGET,
        "analysis_only_columns":
            ANALYSIS_ONLY_COLUMNS,
        "forbidden_model_columns":
            FORBIDDEN_MODEL_COLUMNS,
        "feature_counts": {
            "categorical": len(
                CATEGORICAL_FEATURES
            ),
            "numerical": len(
                NUMERICAL_FEATURES
            ),
            "total": len(
                MODEL_FEATURES
            ),
        },
        "split_summaries":
            split_summaries,
    }

    FEATURE_MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Run all model-input validation checks."""

    validate_feature_configuration()

    datasets = {
        split_name: load_split(
            split_name,
            filename,
        )
        for split_name, filename
        in SPLIT_FILES.items()
    }

    validate_schema_consistency(datasets)

    summaries = []

    print("\n" + "=" * 100)
    print("2. DATASET SPLIT VALIDATION")
    print("=" * 100)

    for split_name, dataframe in datasets.items():
        validate_required_columns(
            dataframe,
            split_name,
        )

        validate_unique_orders(
            dataframe,
            split_name,
        )

        validate_classification_target(
            dataframe,
            split_name,
        )

        validate_regression_target(
            dataframe,
            split_name,
        )

        validate_numerical_feature_types(
            dataframe,
            split_name,
        )

        summary = summarize_split(
            dataframe,
            split_name,
        )

        summaries.append(summary)

    summary_dataframe = pd.DataFrame(
        summaries
    )

    display_summary = summary_dataframe[
        [
            "split",
            "rows",
            "unique_orders",
            "classification_positive_count",
            "classification_positive_rate",
            "regression_target_mean",
            "regression_target_median",
            "missing_feature_values",
        ]
    ].copy()

    display_summary[
        "classification_positive_rate"
    ] *= 100

    print(
        display_summary.to_string(
            index=False,
            formatters={
                "classification_positive_rate":
                    "{:.2f}%".format,
                "regression_target_mean":
                    "{:.2f}".format,
                "regression_target_median":
                    "{:.2f}".format,
            },
        )
    )

    print("\nRequired-column validation:     PASSED")
    print("Unique-order validation:        PASSED")
    print("Classification-target check:    PASSED")
    print("Regression-target check:        PASSED")
    print("Numerical-data-type check:      PASSED")
    print("Split-schema consistency check: PASSED")

    save_feature_manifest(
        summaries
    )

    print("\n" + "=" * 100)
    print("MODEL INPUT VALIDATION COMPLETED")
    print("=" * 100)

    print(
        "\nFeature manifest saved to:\n"
        f"{FEATURE_MANIFEST_PATH}"
    )


if __name__ == "__main__":
    main()