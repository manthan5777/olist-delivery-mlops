from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_DATA_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "model_dataset.parquet"
)

SPLIT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "splits"
)


def load_model_dataset() -> pd.DataFrame:
    """Load and chronologically sort the modelling dataset."""

    if not MODEL_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Model dataset not found: {MODEL_DATA_PATH}"
        )

    dataframe = pd.read_parquet(MODEL_DATA_PATH)

    dataframe["order_purchase_timestamp"] = pd.to_datetime(
        dataframe["order_purchase_timestamp"],
        errors="raise",
    )

    dataframe = dataframe.sort_values(
        by="order_purchase_timestamp",
        ascending=True,
    ).reset_index(drop=True)

    return dataframe


def create_chronological_splits(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split the data chronologically.

    Oldest 70% -> training
    Next 15%   -> validation
    Newest 15% -> testing
    """

    total_rows = len(dataframe)

    train_end = int(total_rows * 0.70)
    validation_end = int(total_rows * 0.85)

    train_data = dataframe.iloc[:train_end].copy()

    validation_data = dataframe.iloc[
        train_end:validation_end
    ].copy()

    test_data = dataframe.iloc[
        validation_end:
    ].copy()

    return train_data, validation_data, test_data


def validate_split_order(
    train_data: pd.DataFrame,
    validation_data: pd.DataFrame,
    test_data: pd.DataFrame,
) -> None:
    """Confirm that the split is truly chronological."""

    train_max = train_data[
        "order_purchase_timestamp"
    ].max()

    validation_min = validation_data[
        "order_purchase_timestamp"
    ].min()

    validation_max = validation_data[
        "order_purchase_timestamp"
    ].max()

    test_min = test_data[
        "order_purchase_timestamp"
    ].min()

    if train_max > validation_min:
        raise ValueError(
            "Training and validation periods overlap."
        )

    if validation_max > test_min:
        raise ValueError(
            "Validation and testing periods overlap."
        )


def summarize_split(
    split_name: str,
    dataframe: pd.DataFrame,
) -> dict:
    """Create a summary for one dataset split."""

    late_count = int(
        dataframe["late_delivery"].sum()
    )

    total_rows = len(dataframe)

    late_percentage = (
        100.0 * late_count / total_rows
        if total_rows > 0
        else 0.0
    )

    return {
        "split": split_name,
        "rows": total_rows,
        "start_date": dataframe[
            "order_purchase_timestamp"
        ].min(),
        "end_date": dataframe[
            "order_purchase_timestamp"
        ].max(),
        "late_orders": late_count,
        "late_percentage": late_percentage,
        "average_delivery_days": dataframe[
            "actual_delivery_days"
        ].mean(),
        "median_delivery_days": dataframe[
            "actual_delivery_days"
        ].median(),
    }


def validate_no_order_overlap(
    train_data: pd.DataFrame,
    validation_data: pd.DataFrame,
    test_data: pd.DataFrame,
) -> None:
    """Verify that an order exists in only one split."""

    train_ids = set(train_data["order_id"])
    validation_ids = set(validation_data["order_id"])
    test_ids = set(test_data["order_id"])

    train_validation_overlap = (
        train_ids.intersection(validation_ids)
    )

    train_test_overlap = train_ids.intersection(test_ids)

    validation_test_overlap = (
        validation_ids.intersection(test_ids)
    )

    if train_validation_overlap:
        raise ValueError(
            "Orders overlap between train and validation."
        )

    if train_test_overlap:
        raise ValueError(
            "Orders overlap between train and test."
        )

    if validation_test_overlap:
        raise ValueError(
            "Orders overlap between validation and test."
        )


def save_splits(
    train_data: pd.DataFrame,
    validation_data: pd.DataFrame,
    test_data: pd.DataFrame,
) -> None:
    """Save each split as a compressed Parquet file."""

    SPLIT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    split_files = {
        "train.parquet": train_data,
        "validation.parquet": validation_data,
        "test.parquet": test_data,
    }

    for filename, split_data in split_files.items():
        output_path = SPLIT_DIRECTORY / filename

        split_data.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
            compression="zstd",
        )

        file_size_mb = (
            output_path.stat().st_size
            / (1024 * 1024)
        )

        print(
            f"Saved {filename:<20} "
            f"{len(split_data):>8,} rows "
            f"| {file_size_mb:.2f} MB"
        )


def verify_total_rows(
    original_data: pd.DataFrame,
    train_data: pd.DataFrame,
    validation_data: pd.DataFrame,
    test_data: pd.DataFrame,
) -> None:
    """Confirm that no records were lost during splitting."""

    split_total = (
        len(train_data)
        + len(validation_data)
        + len(test_data)
    )

    if len(original_data) != split_total:
        raise ValueError(
            "Split row counts do not equal the original dataset."
        )


def main() -> None:
    print(f"Reading:\n{MODEL_DATA_PATH}")

    dataframe = load_model_dataset()

    print("\nCreating chronological splits...")

    (
        train_data,
        validation_data,
        test_data,
    ) = create_chronological_splits(dataframe)

    validate_split_order(
        train_data,
        validation_data,
        test_data,
    )

    validate_no_order_overlap(
        train_data,
        validation_data,
        test_data,
    )

    verify_total_rows(
        dataframe,
        train_data,
        validation_data,
        test_data,
    )

    summaries = [
        summarize_split("train", train_data),
        summarize_split(
            "validation",
            validation_data,
        ),
        summarize_split("test", test_data),
    ]

    summary_dataframe = pd.DataFrame(summaries)

    print("\n" + "=" * 100)
    print("CHRONOLOGICAL SPLIT SUMMARY")
    print("=" * 100)

    print(
        summary_dataframe.to_string(
            index=False,
            formatters={
                "late_percentage": "{:.2f}%".format,
                "average_delivery_days": "{:.2f}".format,
                "median_delivery_days": "{:.2f}".format,
            },
        )
    )

    print("\n" + "=" * 100)
    print("SPLIT VALIDATION")
    print("=" * 100)

    print(
        f"Original rows:   {len(dataframe):,}"
    )
    print(
        f"Training rows:   {len(train_data):,}"
    )
    print(
        f"Validation rows: {len(validation_data):,}"
    )
    print(
        f"Testing rows:    {len(test_data):,}"
    )

    print("\nChronological order: PASSED")
    print("Order overlap check: PASSED")
    print("Total row validation: PASSED")

    print("\n" + "=" * 100)
    print("SAVING SPLITS")
    print("=" * 100)

    save_splits(
        train_data,
        validation_data,
        test_data,
    )

    print("\nData splitting completed.")


if __name__ == "__main__":
    main()