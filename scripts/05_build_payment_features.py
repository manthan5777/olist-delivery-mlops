from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "olist.duckdb"
SQL_PATH = PROJECT_ROOT / "sql" / "02_build_payment_features.sql"


def run_sql_file(
    connection: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Read and execute the payment-feature SQL file."""

    if not sql_path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {sql_path}"
        )

    sql_text = sql_path.read_text(encoding="utf-8")
    connection.execute(sql_text)


def validate_payment_features(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Validate that payment aggregation created one row per order."""

    unique_payment_orders = connection.execute(
        """
        SELECT COUNT(DISTINCT order_id)
        FROM payments
        """
    ).fetchone()[0]

    feature_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM payment_features
        """
    ).fetchone()[0]

    duplicate_orders = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                order_id,
                COUNT(*) AS row_count
            FROM payment_features
            GROUP BY order_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    raw_payment_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM payments
        """
    ).fetchone()[0]

    aggregated_payment_count = connection.execute(
        """
        SELECT SUM(payment_count)
        FROM payment_features
        """
    ).fetchone()[0]

    print("\n" + "=" * 80)
    print("PAYMENT FEATURE VALIDATION")
    print("=" * 80)

    print(
        f"Unique orders in payments:     "
        f"{unique_payment_orders:,}"
    )
    print(
        f"Rows in payment_features:      "
        f"{feature_rows:,}"
    )
    print(
        f"Duplicate order IDs:           "
        f"{duplicate_orders:,}"
    )
    print(
        f"Raw payment rows:              "
        f"{raw_payment_rows:,}"
    )
    print(
        f"Sum of aggregated payments:    "
        f"{aggregated_payment_count:,}"
    )

    if unique_payment_orders != feature_rows:
        raise ValueError(
            "payment_features does not contain exactly "
            "one row per payment order."
        )

    if duplicate_orders != 0:
        raise ValueError(
            "Duplicate order IDs found in payment_features."
        )

    if raw_payment_rows != aggregated_payment_count:
        raise ValueError(
            "Aggregated payment counts do not match raw rows."
        )

    print("Status: PASSED")


def validate_payment_totals(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Confirm payment value was not lost or duplicated."""

    (
        raw_payment_total,
        aggregated_payment_total,
    ) = connection.execute(
        """
        SELECT
            (
                SELECT SUM(payment_value)
                FROM payments
            ) AS raw_payment_total,

            (
                SELECT SUM(total_payment_value)
                FROM payment_features
            ) AS aggregated_payment_total
        """
    ).fetchone()

    difference = abs(
        raw_payment_total - aggregated_payment_total
    )

    print("\n" + "=" * 80)
    print("PAYMENT TOTAL VALIDATION")
    print("=" * 80)

    print(
        f"Raw payment-value total:        "
        f"{raw_payment_total:,.2f}"
    )
    print(
        f"Aggregated payment-value total: "
        f"{aggregated_payment_total:,.2f}"
    )
    print(
        f"Difference:                     "
        f"{difference:,.6f}"
    )

    if difference > 0.01:
        raise ValueError(
            "Raw and aggregated payment totals do not match."
        )

    print("Status: PASSED")


def show_payment_type_distribution(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display payment-method usage in the raw table."""

    result = connection.execute(
        """
        SELECT
            payment_type,
            COUNT(*) AS payment_rows,
            COUNT(DISTINCT order_id) AS order_count,
            ROUND(SUM(payment_value), 2)
                AS total_payment_value
        FROM payments
        GROUP BY payment_type
        ORDER BY payment_rows DESC
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("PAYMENT TYPE DISTRIBUTION")
    print("=" * 80)

    print(result.to_string(index=False))


def show_orders_with_multiple_payments(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Show orders containing the most payment records."""

    result = connection.execute(
        """
        SELECT
            order_id,
            payment_count,
            payment_type_count,
            ROUND(total_payment_value, 2)
                AS total_payment_value,
            maximum_installments,
            primary_payment_type,
            used_credit_card,
            used_voucher,
            used_boleto,
            used_debit_card
        FROM payment_features
        ORDER BY payment_count DESC, order_id
        LIMIT 10
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("SAMPLE: ORDERS WITH THE MOST PAYMENT RECORDS")
    print("=" * 80)

    print(result.to_string(index=False))


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
        print("\nBuilding payment features...")
        run_sql_file(connection, SQL_PATH)

        validate_payment_features(connection)
        validate_payment_totals(connection)
        show_payment_type_distribution(connection)
        show_orders_with_multiple_payments(connection)

        print("\n" + "=" * 80)
        print("PAYMENT FEATURE BUILD COMPLETED")
        print("=" * 80)

        print(
            "\nCreated DuckDB table:\n"
            "  payment_features"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()