from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "olist.duckdb"
)

SQL_PATH = (
    PROJECT_ROOT
    / "sql"
    / "03_build_joined_orders.sql"
)


def run_sql_file(
    connection: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Read and execute the SQL transformation."""

    if not sql_path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {sql_path}"
        )

    sql_text = sql_path.read_text(
        encoding="utf-8"
    )

    connection.execute(sql_text)


def validate_joined_orders(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Verify that the joins did not multiply or remove orders."""

    source_order_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM orders
        """
    ).fetchone()[0]

    joined_order_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM joined_orders
        """
    ).fetchone()[0]

    source_unique_orders = connection.execute(
        """
        SELECT COUNT(DISTINCT order_id)
        FROM orders
        """
    ).fetchone()[0]

    joined_unique_orders = connection.execute(
        """
        SELECT COUNT(DISTINCT order_id)
        FROM joined_orders
        """
    ).fetchone()[0]

    duplicate_order_ids = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                order_id,
                COUNT(*) AS row_count
            FROM joined_orders
            GROUP BY order_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    print("\n" + "=" * 80)
    print("JOINED ORDER VALIDATION")
    print("=" * 80)

    print(
        f"Rows in orders:              "
        f"{source_order_count:,}"
    )

    print(
        f"Rows in joined_orders:       "
        f"{joined_order_count:,}"
    )

    print(
        f"Unique IDs in orders:        "
        f"{source_unique_orders:,}"
    )

    print(
        f"Unique IDs in joined_orders: "
        f"{joined_unique_orders:,}"
    )

    print(
        f"Duplicate order IDs:         "
        f"{duplicate_order_ids:,}"
    )

    if source_order_count != joined_order_count:
        raise ValueError(
            "The joins changed the number of order rows."
        )

    if source_unique_orders != joined_unique_orders:
        raise ValueError(
            "The joins changed the number of unique orders."
        )

    if duplicate_order_ids != 0:
        raise ValueError(
            "Duplicate order IDs were created."
        )

    print("Status: PASSED")


def show_missing_join_information(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Show orders missing item or payment features."""

    result = connection.execute(
        """
        SELECT
            COUNT(*) AS total_orders,

            SUM(
                CASE
                    WHEN has_item_features = 0 THEN 1
                    ELSE 0
                END
            ) AS orders_without_items,

            SUM(
                CASE
                    WHEN has_payment_features = 0 THEN 1
                    ELSE 0
                END
            ) AS orders_without_payments,

            SUM(
                CASE
                    WHEN customer_state IS NULL THEN 1
                    ELSE 0
                END
            ) AS orders_without_customer_state

        FROM joined_orders
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("MISSING JOIN INFORMATION")
    print("=" * 80)

    print(result.to_string(index=False))


def show_missing_information_by_status(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Explain which order statuses lack item or payment data."""

    result = connection.execute(
        """
        SELECT
            order_status,
            COUNT(*) AS total_orders,

            SUM(
                CASE
                    WHEN has_item_features = 0 THEN 1
                    ELSE 0
                END
            ) AS without_items,

            SUM(
                CASE
                    WHEN has_payment_features = 0 THEN 1
                    ELSE 0
                END
            ) AS without_payments

        FROM joined_orders

        GROUP BY order_status

        ORDER BY total_orders DESC
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("MISSING INFORMATION BY ORDER STATUS")
    print("=" * 80)

    print(result.to_string(index=False))


def show_payment_reconciliation(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Compare payment totals with price plus freight."""

    result = connection.execute(
        """
        SELECT
            COUNT(*) AS comparable_orders,

            SUM(
                CASE
                    WHEN ABS(
                        payment_order_value_difference
                    ) <= 0.01
                    THEN 1
                    ELSE 0
                END
            ) AS matching_orders,

            ROUND(
                AVG(
                    ABS(
                        payment_order_value_difference
                    )
                ),
                4
            ) AS average_absolute_difference,

            ROUND(
                MAX(
                    ABS(
                        payment_order_value_difference
                    )
                ),
                2
            ) AS maximum_absolute_difference

        FROM joined_orders

        WHERE total_payment_value IS NOT NULL
          AND total_item_price IS NOT NULL
          AND total_freight IS NOT NULL
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("PAYMENT RECONCILIATION")
    print("=" * 80)

    print(result.to_string(index=False))

    print(
        "\nThis is a business reconciliation check, "
        "not a strict foreign-key validation."
    )


def show_sample_joined_orders(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display a few joined order records."""

    result = connection.execute(
        """
        SELECT
            order_id,
            order_status,
            customer_state,
            primary_seller_state,
            same_state_delivery,
            item_count,
            unique_product_count,
            total_item_price,
            total_freight,
            primary_payment_type,
            maximum_installments,
            total_payment_value
        FROM joined_orders

        WHERE has_item_features = 1
          AND has_payment_features = 1

        ORDER BY order_purchase_timestamp

        LIMIT 10
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("SAMPLE JOINED ORDERS")
    print("=" * 80)

    print(result.to_string(index=False))


def main() -> None:
    print(f"DuckDB database:\n{DATABASE_PATH}")
    print(f"\nSQL file:\n{SQL_PATH}")

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            "DuckDB database not found."
        )

    connection = duckdb.connect(
        str(DATABASE_PATH)
    )

    try:
        print("\nBuilding joined order table...")

        run_sql_file(
            connection,
            SQL_PATH,
        )

        validate_joined_orders(connection)

        show_missing_join_information(connection)

        show_missing_information_by_status(connection)

        show_payment_reconciliation(connection)

        show_sample_joined_orders(connection)

        print("\n" + "=" * 80)
        print("JOINED ORDER BUILD COMPLETED")
        print("=" * 80)

        print(
            "\nCreated DuckDB table:\n"
            "  joined_orders"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()