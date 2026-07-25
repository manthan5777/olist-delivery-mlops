from pathlib import Path

import pandas as pd


# Current project folder:
# olist-delivery-mlops/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Folder containing the original CSV files
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


# Each table, its filename, primary key, and grain
TABLES = {
    "orders": {
        "filename": "olist_orders_dataset.csv",
        "primary_key": ["order_id"],
        "grain": "One row represents one order.",
    },
    "customers": {
        "filename": "olist_customers_dataset.csv",
        "primary_key": ["customer_id"],
        "grain": "One row represents one order-specific customer record.",
    },
    "order_items": {
        "filename": "olist_order_items_dataset.csv",
        "primary_key": ["order_id", "order_item_id"],
        "grain": "One row represents one item inside an order.",
    },
    "products": {
        "filename": "olist_products_dataset.csv",
        "primary_key": ["product_id"],
        "grain": "One row represents one product.",
    },
    "sellers": {
        "filename": "olist_sellers_dataset.csv",
        "primary_key": ["seller_id"],
        "grain": "One row represents one seller.",
    },
    "payments": {
        "filename": "olist_order_payments_dataset.csv",
        "primary_key": ["order_id", "payment_sequential"],
        "grain": "One row represents one payment record for an order.",
    },
}


def inspect_table(
    table_name: str,
    filename: str,
    primary_key: list[str],
    grain: str,
) -> pd.DataFrame:
    """Read and inspect one raw table."""

    file_path = RAW_DATA_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError(
            f"\nMissing file: {file_path}\n"
            "Check that the dataset file is inside data/raw."
        )

    dataframe = pd.read_csv(
        file_path,
        low_memory=False,
    )

    print("\n" + "=" * 90)
    print(f"TABLE: {table_name.upper()}")
    print("=" * 90)

    print(f"File: {filename}")
    print(f"Grain: {grain}")
    print(f"Rows: {len(dataframe):,}")
    print(f"Columns: {len(dataframe.columns)}")

    print("\nPrimary key:")
    print(primary_key)

    null_key_rows = dataframe[primary_key].isna().any(axis=1).sum()

    duplicate_key_rows = dataframe.duplicated(
        subset=primary_key,
        keep="first",
    ).sum()

    print("\nPrimary-key validation:")
    print(f"Rows with a null primary key: {null_key_rows:,}")
    print(
        "Duplicate primary-key rows after first occurrence: "
        f"{duplicate_key_rows:,}"
    )

    print("\nColumns and data types:")

    for column_name, data_type in dataframe.dtypes.items():
        print(f"  {column_name:<40} {data_type}")

    missing_values = dataframe.isna().sum()
    missing_values = missing_values[missing_values > 0]
    missing_values = missing_values.sort_values(ascending=False)

    print("\nMissing values:")

    if missing_values.empty:
        print("  No missing values found.")
    else:
        for column_name, missing_count in missing_values.items():
            missing_percentage = (
                missing_count / len(dataframe)
            ) * 100

            print(
                f"  {column_name:<40} "
                f"{missing_count:>8,} "
                f"({missing_percentage:.2f}%)"
            )

    print("\nFirst two rows:")
    print(dataframe.head(2).to_string(index=False))

    return dataframe


def main() -> None:
    """Inspect all raw Olist tables."""

    print(f"Reading data from:\n{RAW_DATA_DIR}")

    loaded_tables = {}

    for table_name, table_config in TABLES.items():
        loaded_tables[table_name] = inspect_table(
            table_name=table_name,
            filename=table_config["filename"],
            primary_key=table_config["primary_key"],
            grain=table_config["grain"],
        )

    print("\n" + "=" * 90)
    print("RAW TABLE INSPECTION COMPLETED")
    print("=" * 90)

    print("\nRow-count comparison:")

    for table_name, dataframe in loaded_tables.items():
        print(f"  {table_name:<20} {len(dataframe):>10,}")

    print(
        "\nImportant observation:\n"
        "The order_items and payments tables can contain multiple rows "
        "for the same order.\n"
        "Therefore, they must be aggregated before they are joined "
        "to the orders table."
    )


if __name__ == "__main__":
    main()