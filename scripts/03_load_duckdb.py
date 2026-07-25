from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DATABASE_PATH = PROJECT_ROOT / "data" / "olist.duckdb"


TABLE_FILES = {
    "orders": "olist_orders_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
}


def escape_sql_path(file_path: Path) -> str:
    """
    Convert a Windows path into a SQL-safe path.

    DuckDB accepts forward slashes on Windows.
    """
    return file_path.resolve().as_posix().replace("'", "''")


def create_database_tables(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Load every raw CSV into a physical DuckDB table."""

    print("\nCreating DuckDB tables...")

    for table_name, filename in TABLE_FILES.items():
        file_path = RAW_DATA_DIR / filename

        if not file_path.exists():
            raise FileNotFoundError(
                f"Missing source file: {file_path}"
            )

        sql_file_path = escape_sql_path(file_path)

        print(f"Loading {filename} → {table_name}")

        connection.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT *
            FROM read_csv_auto(
                '{sql_file_path}',
                header = true,
                sample_size = -1
            );
            """
        )


def validate_loaded_tables(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display row and column counts for loaded tables."""

    print("\n" + "=" * 80)
    print("DUCKDB TABLE VALIDATION")
    print("=" * 80)

    for table_name in TABLE_FILES:
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        column_count = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = '{table_name}'
            """
        ).fetchone()[0]

        print(
            f"{table_name:<20}"
            f" rows: {row_count:>10,}"
            f" | columns: {column_count:>3}"
        )


def show_database_tables(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """List every table stored inside the DuckDB database."""

    tables = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()

    print("\nTables stored inside the database:")

    for table in tables:
        print(f"  - {table[0]}")


def show_sample_query(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Run one simple SQL query as a database test."""

    print("\n" + "=" * 80)
    print("SAMPLE SQL QUERY")
    print("=" * 80)

    result = connection.execute(
        """
        SELECT
            order_status,
            COUNT(*) AS order_count
        FROM orders
        GROUP BY order_status
        ORDER BY order_count DESC
        """
    ).fetchdf()

    print(result.to_string(index=False))


def main() -> None:
    print(f"Raw data directory:\n{RAW_DATA_DIR}")
    print(f"\nDuckDB database file:\n{DATABASE_PATH}")

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = duckdb.connect(str(DATABASE_PATH))

    try:
        create_database_tables(connection)
        validate_loaded_tables(connection)
        show_database_tables(connection)
        show_sample_query(connection)

        print("\n" + "=" * 80)
        print("DUCKDB LOAD COMPLETED")
        print("=" * 80)

        print(
            "\nThe CSV files remain unchanged.\n"
            "The six tables are now stored inside data/olist.duckdb."
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()