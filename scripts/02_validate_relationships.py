from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


FILES = {
    "orders": "olist_orders_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
}


def load_tables() -> dict[str, pd.DataFrame]:
    """Load only the columns required for relationship validation."""

    tables = {
        "orders": pd.read_csv(
            RAW_DATA_DIR / FILES["orders"],
            usecols=["order_id", "customer_id"],
        ),
        "customers": pd.read_csv(
            RAW_DATA_DIR / FILES["customers"],
            usecols=["customer_id"],
        ),
        "order_items": pd.read_csv(
            RAW_DATA_DIR / FILES["order_items"],
            usecols=["order_id", "product_id", "seller_id"],
        ),
        "products": pd.read_csv(
            RAW_DATA_DIR / FILES["products"],
            usecols=["product_id"],
        ),
        "sellers": pd.read_csv(
            RAW_DATA_DIR / FILES["sellers"],
            usecols=["seller_id"],
        ),
        "payments": pd.read_csv(
            RAW_DATA_DIR / FILES["payments"],
            usecols=["order_id"],
        ),
    }

    return tables


def validate_relationship(
    relationship_name: str,
    child_values: pd.Series,
    parent_values: pd.Series,
) -> None:
    """Check whether every child key exists in the parent table."""

    parent_key_set = set(parent_values.dropna().unique())

    orphan_mask = ~child_values.isin(parent_key_set)
    orphan_rows = child_values[orphan_mask]

    print("\n" + "-" * 90)
    print(f"Relationship: {relationship_name}")
    print("-" * 90)

    print(f"Child rows checked: {len(child_values):,}")
    print(f"Unique child keys: {child_values.nunique(dropna=True):,}")
    print(f"Unique parent keys: {parent_values.nunique(dropna=True):,}")
    print(f"Unmatched child rows: {len(orphan_rows):,}")
    print(f"Unique unmatched keys: {orphan_rows.nunique(dropna=True):,}")

    if orphan_rows.empty:
        print("Status: PASSED")
    else:
        print("Status: FAILED")
        print("\nFirst five unmatched keys:")
        print(orphan_rows.drop_duplicates().head(5).to_string(index=False))


def show_order_multiplicity(
    table_name: str,
    order_ids: pd.Series,
) -> None:
    """Show how many orders appear once or multiple times."""

    order_counts = order_ids.value_counts()

    orders_with_one_row = int((order_counts == 1).sum())
    orders_with_multiple_rows = int((order_counts > 1).sum())
    maximum_rows_per_order = int(order_counts.max())

    print("\n" + "-" * 90)
    print(f"ORDER MULTIPLICITY: {table_name.upper()}")
    print("-" * 90)

    print(f"Unique orders: {len(order_counts):,}")
    print(f"Orders appearing once: {orders_with_one_row:,}")
    print(
        f"Orders appearing multiple times: "
        f"{orders_with_multiple_rows:,}"
    )
    print(
        f"Maximum rows for one order: "
        f"{maximum_rows_per_order:,}"
    )

    print("\nTop five orders by row count:")
    print(order_counts.head(5).to_string())


def main() -> None:
    print(f"Reading raw data from:\n{RAW_DATA_DIR}")

    tables = load_tables()

    print("\n" + "=" * 90)
    print("FOREIGN-KEY VALIDATION")
    print("=" * 90)

    validate_relationship(
        relationship_name=(
            "orders.customer_id → customers.customer_id"
        ),
        child_values=tables["orders"]["customer_id"],
        parent_values=tables["customers"]["customer_id"],
    )

    validate_relationship(
        relationship_name=(
            "order_items.order_id → orders.order_id"
        ),
        child_values=tables["order_items"]["order_id"],
        parent_values=tables["orders"]["order_id"],
    )

    validate_relationship(
        relationship_name=(
            "order_items.product_id → products.product_id"
        ),
        child_values=tables["order_items"]["product_id"],
        parent_values=tables["products"]["product_id"],
    )

    validate_relationship(
        relationship_name=(
            "order_items.seller_id → sellers.seller_id"
        ),
        child_values=tables["order_items"]["seller_id"],
        parent_values=tables["sellers"]["seller_id"],
    )

    validate_relationship(
        relationship_name=(
            "payments.order_id → orders.order_id"
        ),
        child_values=tables["payments"]["order_id"],
        parent_values=tables["orders"]["order_id"],
    )

    print("\n" + "=" * 90)
    print("ONE-TO-MANY CHECKS")
    print("=" * 90)

    show_order_multiplicity(
        table_name="order_items",
        order_ids=tables["order_items"]["order_id"],
    )

    show_order_multiplicity(
        table_name="payments",
        order_ids=tables["payments"]["order_id"],
    )

    print("\n" + "=" * 90)
    print("RELATIONSHIP VALIDATION COMPLETED")
    print("=" * 90)


if __name__ == "__main__":
    main()