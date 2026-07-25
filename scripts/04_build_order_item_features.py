from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "olist.duckdb"
SQL_PATH = (
    PROJECT_ROOT
    / "sql"
    / "01_build_order_item_features.sql"
)


def run_sql_file(
    connection: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Read and execute a SQL file."""

    if not sql_path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {sql_path}"
        )

    sql_text = sql_path.read_text(encoding="utf-8")
    connection.execute(sql_text)


def validate_enriched_items(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Validate that item joins did not create or remove rows."""

    source_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM order_items
        """
    ).fetchone()[0]

    enriched_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM enriched_order_items
        """
    ).fetchone()[0]

    print("\n" + "=" * 80)
    print("ENRICHED ITEM VALIDATION")
    print("=" * 80)

    print(f"Raw order-item rows:      {source_count:,}")
    print(f"Enriched order-item rows: {enriched_count:,}")

    if source_count != enriched_count:
        raise ValueError(
            "The item join changed the number of rows. "
            "This may indicate duplicate product or seller keys."
        )

    print("Status: PASSED")


def validate_order_features(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Validate the one-row-per-order feature table."""

    unique_source_orders = connection.execute(
        """
        SELECT COUNT(DISTINCT order_id)
        FROM order_items
        """
    ).fetchone()[0]

    feature_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM order_item_features
        """
    ).fetchone()[0]

    duplicate_orders = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                order_id,
                COUNT(*) AS row_count
            FROM order_item_features
            GROUP BY order_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    aggregated_item_count = connection.execute(
        """
        SELECT SUM(item_count)
        FROM order_item_features
        """
    ).fetchone()[0]

    raw_item_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM order_items
        """
    ).fetchone()[0]

    print("\n" + "=" * 80)
    print("ORDER-LEVEL FEATURE VALIDATION")
    print("=" * 80)

    print(
        f"Unique orders in order_items: "
        f"{unique_source_orders:,}"
    )
    print(
        f"Rows in order_item_features:  "
        f"{feature_rows:,}"
    )
    print(
        f"Duplicate order IDs:           "
        f"{duplicate_orders:,}"
    )
    print(
        f"Raw item rows:                 "
        f"{raw_item_count:,}"
    )
    print(
        f"Sum of aggregated item_count: "
        f"{aggregated_item_count:,}"
    )

    if unique_source_orders != feature_rows:
        raise ValueError(
            "Feature table does not contain exactly "
            "one row per source order."
        )

    if duplicate_orders != 0:
        raise ValueError(
            "Duplicate order IDs found in order_item_features."
        )

    if raw_item_count != aggregated_item_count:
        raise ValueError(
            "Aggregated item counts do not match raw item rows."
        )

    print("Status: PASSED")


def validate_financial_totals(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Compare raw totals with aggregated totals."""

    totals = connection.execute(
        """
        SELECT
            (
                SELECT SUM(price)
                FROM order_items
            ) AS raw_price_total,

            (
                SELECT SUM(total_item_price)
                FROM order_item_features
            ) AS aggregated_price_total,

            (
                SELECT SUM(freight_value)
                FROM order_items
            ) AS raw_freight_total,

            (
                SELECT SUM(total_freight)
                FROM order_item_features
            ) AS aggregated_freight_total
        """
    ).fetchone()

    (
        raw_price_total,
        aggregated_price_total,
        raw_freight_total,
        aggregated_freight_total,
    ) = totals

    print("\n" + "=" * 80)
    print("TOTAL VALIDATION")
    print("=" * 80)

    print(f"Raw price total:        {raw_price_total:,.2f}")
    print(
        f"Aggregated price total: "
        f"{aggregated_price_total:,.2f}"
    )

    print(f"Raw freight total:      {raw_freight_total:,.2f}")
    print(
        f"Aggregated freight:     "
        f"{aggregated_freight_total:,.2f}"
    )

    price_difference = abs(
        raw_price_total - aggregated_price_total
    )

    freight_difference = abs(
        raw_freight_total - aggregated_freight_total
    )

    if price_difference > 0.01:
        raise ValueError(
            "Raw and aggregated price totals do not match."
        )

    if freight_difference > 0.01:
        raise ValueError(
            "Raw and aggregated freight totals do not match."
        )

    print("Status: PASSED")


def show_sample_orders(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Show orders containing the most items."""

    sample = connection.execute(
        """
        SELECT
            order_id,
            item_count,
            unique_product_count,
            unique_seller_count,
            unique_category_count,
            ROUND(total_item_price, 2)
                AS total_item_price,
            ROUND(total_freight, 2)
                AS total_freight,
            ROUND(freight_to_price_ratio, 4)
                AS freight_to_price_ratio,
            ROUND(total_product_weight_g, 2)
                AS total_product_weight_g,
            primary_seller_state
        FROM order_item_features
        ORDER BY item_count DESC, order_id
        LIMIT 10
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("SAMPLE: ORDERS WITH THE MOST ITEMS")
    print("=" * 80)

    print(sample.to_string(index=False))


def main() -> None:
    print(f"DuckDB database:\n{DATABASE_PATH}")
    print(f"\nSQL file:\n{SQL_PATH}")

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            "DuckDB database not found. "
            "Run scripts/03_load_duckdb.py first."
        )

    connection = duckdb.connect(str(DATABASE_PATH))

    try:
        print("\nBuilding order-item features...")
        run_sql_file(connection, SQL_PATH)

        validate_enriched_items(connection)
        validate_order_features(connection)
        validate_financial_totals(connection)
        show_sample_orders(connection)

        print("\n" + "=" * 80)
        print("ORDER-ITEM FEATURE BUILD COMPLETED")
        print("=" * 80)

        print(
            "\nCreated DuckDB tables:\n"
            "  1. enriched_order_items\n"
            "  2. order_item_features"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()