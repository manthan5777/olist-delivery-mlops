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
    / "04_build_model_dataset.sql"
)

PARQUET_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "model_dataset.parquet"
)


def run_sql_file(
    connection: duckdb.DuckDBPyConnection,
    sql_path: Path,
) -> None:
    """Execute the model-dataset SQL transformation."""

    if not sql_path.exists():
        raise FileNotFoundError(
            f"SQL file not found: {sql_path}"
        )

    sql_text = sql_path.read_text(
        encoding="utf-8"
    )

    connection.execute(sql_text)


def validate_model_dataset(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Validate uniqueness, targets and delivery durations."""

    summary = connection.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT order_id) AS unique_orders,

            SUM(
                CASE
                    WHEN late_delivery = 1 THEN 1
                    ELSE 0
                END
            ) AS late_orders,

            SUM(
                CASE
                    WHEN late_delivery = 0 THEN 1
                    ELSE 0
                END
            ) AS on_time_orders,

            SUM(
                CASE
                    WHEN actual_delivery_days IS NULL THEN 1
                    ELSE 0
                END
            ) AS missing_regression_targets,

            SUM(
                CASE
                    WHEN late_delivery IS NULL THEN 1
                    ELSE 0
                END
            ) AS missing_classification_targets,

            SUM(
                CASE
                    WHEN actual_delivery_days < 0 THEN 1
                    ELSE 0
                END
            ) AS negative_delivery_durations

        FROM model_dataset
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("MODEL DATASET VALIDATION")
    print("=" * 80)

    print(summary.to_string(index=False))

    row = summary.iloc[0]

    if row["total_rows"] != row["unique_orders"]:
        raise ValueError(
            "The model dataset does not contain "
            "one unique row per order."
        )

    if row["missing_regression_targets"] != 0:
        raise ValueError(
            "Missing regression targets were found."
        )

    if row["missing_classification_targets"] != 0:
        raise ValueError(
            "Missing classification targets were found."
        )

    if row["negative_delivery_durations"] != 0:
        raise ValueError(
            "Negative delivery durations were found."
        )

    print("Status: PASSED")


def show_target_distribution(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display classification and regression target statistics."""

    classification = connection.execute(
        """
        SELECT
            late_delivery,
            COUNT(*) AS order_count,
            ROUND(
                100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
                2
            ) AS percentage
        FROM model_dataset
        GROUP BY late_delivery
        ORDER BY late_delivery
        """
    ).fetchdf()

    regression = connection.execute(
        """
        SELECT
            ROUND(MIN(actual_delivery_days), 2)
                AS minimum_days,

            ROUND(AVG(actual_delivery_days), 2)
                AS average_days,

            ROUND(MEDIAN(actual_delivery_days), 2)
                AS median_days,

            ROUND(
                QUANTILE_CONT(actual_delivery_days, 0.95),
                2
            ) AS p95_days,

            ROUND(MAX(actual_delivery_days), 2)
                AS maximum_days

        FROM model_dataset
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("CLASSIFICATION TARGET DISTRIBUTION")
    print("=" * 80)

    print(classification.to_string(index=False))

    print("\n" + "=" * 80)
    print("REGRESSION TARGET DISTRIBUTION")
    print("=" * 80)

    print(regression.to_string(index=False))


def show_date_range(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Show the historical period available for splitting."""

    result = connection.execute(
        """
        SELECT
            MIN(order_purchase_timestamp)
                AS earliest_purchase,

            MAX(order_purchase_timestamp)
                AS latest_purchase,

            COUNT(DISTINCT purchase_year)
                AS number_of_years

        FROM model_dataset
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("DATASET DATE RANGE")
    print("=" * 80)

    print(result.to_string(index=False))


def show_missing_feature_summary(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display missing values in important model features."""

    result = connection.execute(
        """
        SELECT
            SUM(
                CASE WHEN customer_state IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_customer_state,

            SUM(
                CASE WHEN primary_seller_state IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_seller_state,

            SUM(
                CASE WHEN total_product_weight_g IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_weight,

            SUM(
                CASE WHEN total_product_volume_cm3 IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_volume,

            SUM(
                CASE WHEN primary_payment_type IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_payment_type,

            SUM(
                CASE WHEN approval_delay_hours IS NULL
                THEN 1 ELSE 0 END
            ) AS missing_approval_delay

        FROM model_dataset
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("IMPORTANT FEATURE MISSING VALUES")
    print("=" * 80)

    print(result.to_string(index=False))


def export_to_parquet(
    connection: duckdb.DuckDBPyConnection,
    parquet_path: Path,
) -> None:
    """Export the final model dataset to Parquet."""

    parquet_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sql_path = (
        parquet_path.resolve()
        .as_posix()
        .replace("'", "''")
    )

    connection.execute(
        f"""
        COPY model_dataset
        TO '{sql_path}'
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD
        );
        """
    )

    print("\n" + "=" * 80)
    print("PARQUET EXPORT")
    print("=" * 80)

    print(f"Saved to:\n{parquet_path}")
    print(
        f"File size: "
        f"{parquet_path.stat().st_size / (1024 * 1024):.2f} MB"
    )


def compare_duckdb_and_parquet(
    connection: duckdb.DuckDBPyConnection,
    parquet_path: Path,
) -> None:
    """Confirm the Parquet export contains the same number of rows."""

    sql_path = (
        parquet_path.resolve()
        .as_posix()
        .replace("'", "''")
    )

    duckdb_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM model_dataset
        """
    ).fetchone()[0]

    parquet_rows = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{sql_path}')
        """
    ).fetchone()[0]

    print("\nDuckDB table rows:", f"{duckdb_rows:,}")
    print("Parquet file rows:", f"{parquet_rows:,}")

    if duckdb_rows != parquet_rows:
        raise ValueError(
            "DuckDB and Parquet row counts do not match."
        )

    print("Parquet row validation: PASSED")


def show_sample_rows(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Display sample modelling records clearly."""

    sample = connection.execute(
        """
        SELECT
            order_id,
            order_purchase_timestamp,
            customer_state,
            primary_seller_state,
            same_state_delivery,
            item_count,
            ROUND(total_item_price, 2)
                AS total_item_price,
            ROUND(total_freight, 2)
                AS total_freight,
            primary_payment_type,
            maximum_installments,
            ROUND(promised_delivery_days, 2)
                AS promised_delivery_days,
            ROUND(actual_delivery_days, 2)
                AS actual_delivery_days,
            late_delivery
        FROM model_dataset
        ORDER BY order_purchase_timestamp
        LIMIT 10
        """
    ).fetchdf()

    print("\n" + "=" * 80)
    print("SAMPLE MODEL RECORDS")
    print("=" * 80)

    print(sample.to_string(index=False))


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
        print("\nBuilding the final model dataset...")

        run_sql_file(
            connection,
            SQL_PATH,
        )

        validate_model_dataset(connection)
        show_target_distribution(connection)
        show_date_range(connection)
        show_missing_feature_summary(connection)
        show_sample_rows(connection)

        export_to_parquet(
            connection,
            PARQUET_PATH,
        )

        compare_duckdb_and_parquet(
            connection,
            PARQUET_PATH,
        )

        print("\n" + "=" * 80)
        print("MODEL DATASET BUILD COMPLETED")
        print("=" * 80)

        print(
            "\nCreated:\n"
            "  DuckDB table: model_dataset\n"
            "  Parquet file: data/processed/model_dataset.parquet"
        )

    finally:
        connection.close()


if __name__ == "__main__":
    main()