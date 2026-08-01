"""Generate training-data EDA reports without using test data or validation targets."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.feature_config import (  # noqa: E402
    CATEGORICAL_FEATURES,
    CLASSIFICATION_TARGET,
    MODEL_FEATURES,
    NUMERICAL_FEATURES,
    REGRESSION_TARGET,
)


SPLIT_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "splits"
TRAIN_PATH = SPLIT_DIRECTORY / "train.parquet"
VALIDATION_PATH = SPLIT_DIRECTORY / "validation.parquet"
REPORT_DIRECTORY = PROJECT_ROOT / "reports" / "improved" / "eda"

MISSING_VALUES_PATH = REPORT_DIRECTORY / "missing_values.csv"
NUMERICAL_SUMMARY_PATH = REPORT_DIRECTORY / "numerical_summary.csv"
CATEGORICAL_SUMMARY_PATH = REPORT_DIRECTORY / "categorical_summary.csv"
FEATURE_TARGET_SUMMARY_PATH = REPORT_DIRECTORY / "feature_target_summary.csv"
DRIFT_SUMMARY_PATH = REPORT_DIRECTORY / "drift_summary.csv"
REDUNDANT_COLUMNS_PATH = REPORT_DIRECTORY / "redundant_columns.csv"
SUMMARY_PATH = REPORT_DIRECTORY / "eda_summary.md"

PLOT_DPI = 140
TOP_CATEGORIES = 12


def load_split(path: Path) -> pd.DataFrame:
    """Load one prepared dataset split and validate its expected schema."""

    if not path.exists():
        raise FileNotFoundError(f"Required split is missing: {path}")

    dataframe = pd.read_parquet(path)
    required_columns = set(MODEL_FEATURES) | {
        CLASSIFICATION_TARGET,
        REGRESSION_TARGET,
        "order_purchase_timestamp",
    }
    missing_columns = sorted(required_columns - set(dataframe.columns))

    if missing_columns:
        raise ValueError(
            "Prepared split is missing expected columns: "
            f"{missing_columns}"
        )

    dataframe["order_purchase_timestamp"] = pd.to_datetime(
        dataframe["order_purchase_timestamp"],
        errors="raise",
    )
    return dataframe


def save_figure(filename: str) -> None:
    """Save and close the current matplotlib figure."""

    plt.tight_layout()
    plt.savefig(REPORT_DIRECTORY / filename, dpi=PLOT_DPI, bbox_inches="tight")
    plt.close()


def prepare_derived_features(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Add reporting-only groups without changing the supplied source data."""

    result = dataframe.copy()
    result["purchase_period"] = result["order_purchase_timestamp"].dt.to_period("M").astype(str)
    result["delivery_scope"] = np.where(
        result["same_state_delivery"].eq(1),
        "same_state",
        "cross_state_or_missing",
    )
    result["multi_item_group"] = np.where(
        result["item_count"].gt(1), "multi_item", "single_item"
    )
    result["multi_seller_group"] = np.where(
        result["unique_seller_count"].gt(1), "multi_seller", "single_seller"
    )
    result["seller_customer_route"] = (
        result["primary_seller_state"].fillna("missing")
        + "->"
        + result["customer_state"].fillna("missing")
    )
    return result


def create_missing_value_report(train_data: pd.DataFrame) -> pd.DataFrame:
    """Calculate missingness for every train column."""

    report = pd.DataFrame(
        {
            "column": train_data.columns,
            "missing_count": train_data.isna().sum().to_numpy(),
            "missing_rate": train_data.isna().mean().to_numpy(),
            "dtype": train_data.dtypes.astype(str).to_numpy(),
        }
    ).sort_values(["missing_rate", "column"], ascending=[False, True])
    report.to_csv(MISSING_VALUES_PATH, index=False)
    return report


def create_numerical_summary(train_data: pd.DataFrame) -> pd.DataFrame:
    """Summarize numeric inputs and both targets, including tails and skew."""

    summary_rows: list[dict[str, float | int | str]] = []
    numerical_columns = NUMERICAL_FEATURES + [
        CLASSIFICATION_TARGET,
        REGRESSION_TARGET,
    ]

    for column in numerical_columns:
        values = pd.to_numeric(train_data[column], errors="coerce")
        non_missing = values.dropna()

        if non_missing.empty:
            summary_rows.append(
                {
                    "column": column,
                    "non_missing_count": 0,
                    "missing_count": int(values.isna().sum()),
                    "mean": np.nan,
                    "std": np.nan,
                    "minimum": np.nan,
                    "p01": np.nan,
                    "p05": np.nan,
                    "p25": np.nan,
                    "median": np.nan,
                    "p75": np.nan,
                    "p95": np.nan,
                    "p99": np.nan,
                    "maximum": np.nan,
                    "skewness": np.nan,
                    "iqr_outlier_count": 0,
                    "negative_count": 0,
                }
            )
            continue

        q1, q3 = non_missing.quantile([0.25, 0.75])
        iqr = q3 - q1
        upper_bound = q3 + 1.5 * iqr
        lower_bound = q1 - 1.5 * iqr
        quantiles = non_missing.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        summary_rows.append(
            {
                "column": column,
                "non_missing_count": int(non_missing.size),
                "missing_count": int(values.isna().sum()),
                "mean": float(non_missing.mean()),
                "std": float(non_missing.std()),
                "minimum": float(non_missing.min()),
                "p01": float(quantiles.loc[0.01]),
                "p05": float(quantiles.loc[0.05]),
                "p25": float(quantiles.loc[0.25]),
                "median": float(quantiles.loc[0.5]),
                "p75": float(quantiles.loc[0.75]),
                "p95": float(quantiles.loc[0.95]),
                "p99": float(quantiles.loc[0.99]),
                "maximum": float(non_missing.max()),
                "skewness": float(non_missing.skew()),
                "iqr_outlier_count": int(
                    ((non_missing < lower_bound) | (non_missing > upper_bound)).sum()
                ),
                "negative_count": int((non_missing < 0).sum()),
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values("column")
    summary.to_csv(NUMERICAL_SUMMARY_PATH, index=False)
    return summary


def create_categorical_summary(train_data: pd.DataFrame) -> pd.DataFrame:
    """Write categorical frequencies for configured and reporting group columns."""

    reporting_columns = CATEGORICAL_FEATURES + [
        "delivery_scope",
        "multi_item_group",
        "multi_seller_group",
        "seller_customer_route",
    ]
    rows: list[dict[str, float | int | str]] = []

    for column in reporting_columns:
        values = train_data[column].fillna("<missing>").astype(str)
        frequencies = values.value_counts(dropna=False)

        for category, count in frequencies.items():
            rows.append(
                {
                    "feature": column,
                    "category": category,
                    "count": int(count),
                    "rate": float(count / len(train_data)),
                    "rank": int(frequencies.index.get_loc(category) + 1),
                }
            )

    summary = pd.DataFrame(rows).sort_values(["feature", "rank"])
    summary.to_csv(CATEGORICAL_SUMMARY_PATH, index=False)
    return summary


def grouped_target_rows(
    train_data: pd.DataFrame,
    feature: str,
    group: pd.Series,
    group_type: str,
) -> list[dict[str, float | int | str]]:
    """Produce classification and regression target summaries for one grouping."""

    normalized_group = group.astype(object).where(
        group.notna(),
        "<missing>",
    ).astype(str)
    summary = (
        train_data.assign(_group=normalized_group)
        .groupby("_group", observed=True)
        .agg(
            order_count=(CLASSIFICATION_TARGET, "size"),
            late_delivery_rate=(CLASSIFICATION_TARGET, "mean"),
            mean_actual_delivery_days=(REGRESSION_TARGET, "mean"),
            median_actual_delivery_days=(REGRESSION_TARGET, "median"),
        )
        .reset_index()
        .rename(columns={"_group": "group"})
    )
    summary["feature"] = feature
    summary["group_type"] = group_type
    return summary[
        [
            "feature",
            "group_type",
            "group",
            "order_count",
            "late_delivery_rate",
            "mean_actual_delivery_days",
            "median_actual_delivery_days",
        ]
    ].to_dict("records")


def create_feature_target_summary(train_data: pd.DataFrame) -> pd.DataFrame:
    """Compare both targets across categories and quantile groups on train only."""

    rows: list[dict[str, float | int | str]] = []
    grouped_features = CATEGORICAL_FEATURES + [
        "delivery_scope",
        "multi_item_group",
        "multi_seller_group",
    ]

    for feature in grouped_features:
        rows.extend(grouped_target_rows(train_data, feature, train_data[feature], "category"))

    for feature in NUMERICAL_FEATURES:
        values = train_data[feature]
        if values.nunique(dropna=True) < 4:
            groups = values.fillna(-1).astype(str)
            group_type = "value"
        else:
            try:
                groups = pd.qcut(values, q=4, duplicates="drop")
                group_type = "quartile"
            except ValueError:
                continue
        rows.extend(grouped_target_rows(train_data, feature, groups, group_type))

    route_counts = train_data["seller_customer_route"].value_counts()
    top_routes = route_counts.head(TOP_CATEGORIES).index
    route_group = train_data["seller_customer_route"].where(
        train_data["seller_customer_route"].isin(top_routes), "other_route"
    )
    rows.extend(grouped_target_rows(train_data, "seller_customer_route", route_group, "top_route"))

    summary = pd.DataFrame(rows).sort_values(["feature", "group_type", "group"])
    summary.to_csv(FEATURE_TARGET_SUMMARY_PATH, index=False)
    return summary


def population_stability_index(train_values: pd.Series, validation_values: pd.Series) -> float:
    """Calculate a bounded-bin PSI using train-derived quantile boundaries."""

    train_non_missing = train_values.dropna()
    validation_non_missing = validation_values.dropna()
    if train_non_missing.empty or validation_non_missing.empty:
        return np.nan

    boundaries = np.unique(train_non_missing.quantile(np.linspace(0, 1, 11)).to_numpy())
    if len(boundaries) < 2:
        return 0.0

    boundaries[0] = -np.inf
    boundaries[-1] = np.inf
    train_bins = pd.cut(train_non_missing, bins=boundaries, include_lowest=True)
    validation_bins = pd.cut(validation_non_missing, bins=boundaries, include_lowest=True)
    train_distribution = train_bins.value_counts(sort=False, normalize=True)
    validation_distribution = validation_bins.value_counts(sort=False, normalize=True)
    epsilon = 1e-6
    return float(
        ((validation_distribution + epsilon - (train_distribution + epsilon))
        * np.log((validation_distribution + epsilon) / (train_distribution + epsilon))).sum()
    )


def create_drift_summary(train_data: pd.DataFrame, validation_data: pd.DataFrame) -> pd.DataFrame:
    """Compare feature distributions without reading validation target columns."""

    rows: list[dict[str, float | int | str]] = []
    for feature in NUMERICAL_FEATURES:
        train_values = pd.to_numeric(train_data[feature], errors="coerce")
        validation_values = pd.to_numeric(validation_data[feature], errors="coerce")
        rows.append(
            {
                "feature": feature,
                "feature_type": "numeric",
                "train_missing_rate": float(train_values.isna().mean()),
                "validation_missing_rate": float(validation_values.isna().mean()),
                "train_mean": float(train_values.mean()),
                "validation_mean": float(validation_values.mean()),
                "mean_difference": float(validation_values.mean() - train_values.mean()),
                "psi_or_tvd": population_stability_index(train_values, validation_values),
                "validation_unseen_rate": 0.0,
            }
        )

    for feature in CATEGORICAL_FEATURES:
        train_values = train_data[feature].fillna("<missing>").astype(str)
        validation_values = validation_data[feature].fillna("<missing>").astype(str)
        categories = train_values.unique()
        train_distribution = train_values.value_counts(normalize=True)
        validation_distribution = validation_values.value_counts(normalize=True)
        all_categories = train_distribution.index.union(validation_distribution.index)
        tvd = 0.5 * (
            train_distribution.reindex(all_categories, fill_value=0)
            - validation_distribution.reindex(all_categories, fill_value=0)
        ).abs().sum()
        rows.append(
            {
                "feature": feature,
                "feature_type": "categorical",
                "train_missing_rate": float(train_data[feature].isna().mean()),
                "validation_missing_rate": float(validation_data[feature].isna().mean()),
                "train_mean": np.nan,
                "validation_mean": np.nan,
                "mean_difference": np.nan,
                "psi_or_tvd": float(tvd),
                "validation_unseen_rate": float((~validation_values.isin(categories)).mean()),
            }
        )

    summary = pd.DataFrame(rows).sort_values("psi_or_tvd", ascending=False)
    summary.to_csv(DRIFT_SUMMARY_PATH, index=False)
    return summary


def create_redundant_column_report(train_data: pd.DataFrame) -> pd.DataFrame:
    """Find highly correlated numeric inputs and exact duplicate input columns."""

    numeric_inputs = train_data[NUMERICAL_FEATURES]
    correlation = numeric_inputs.corr(method="spearman", min_periods=100)
    rows: list[dict[str, float | str]] = []

    for left_index, left_column in enumerate(correlation.columns):
        for right_column in correlation.columns[left_index + 1 :]:
            value = correlation.loc[left_column, right_column]
            if pd.notna(value) and abs(value) >= 0.95:
                rows.append(
                    {
                        "relationship": "high_spearman_correlation",
                        "left_column": left_column,
                        "right_column": right_column,
                        "value": float(value),
                    }
                )

    for left_index, left_column in enumerate(MODEL_FEATURES):
        for right_column in MODEL_FEATURES[left_index + 1 :]:
            if train_data[left_column].equals(train_data[right_column]):
                rows.append(
                    {
                        "relationship": "exact_duplicate",
                        "left_column": left_column,
                        "right_column": right_column,
                        "value": 1.0,
                    }
                )

    report = pd.DataFrame(
        rows,
        columns=["relationship", "left_column", "right_column", "value"],
    )
    report.to_csv(REDUNDANT_COLUMNS_PATH, index=False)
    return report


def plot_target_distributions(train_data: pd.DataFrame) -> None:
    """Plot class imbalance and the observed delivery-duration distribution."""

    class_counts = train_data[CLASSIFICATION_TARGET].value_counts().sort_index()
    plt.figure(figsize=(7, 4))
    plt.bar(["on_time", "late"], [class_counts.get(0, 0), class_counts.get(1, 0)], color=["#457b9d", "#e76f51"])
    plt.title("Training Classification Target Distribution")
    plt.ylabel("Orders")
    save_figure("target_classification_distribution.png")

    plt.figure(figsize=(8, 4))
    plt.hist(train_data[REGRESSION_TARGET].dropna(), bins=50, color="#2a9d8f", edgecolor="white")
    plt.title("Training Actual Delivery Days Distribution")
    plt.xlabel("Days")
    plt.ylabel("Orders")
    save_figure("target_regression_distribution.png")


def plot_monthly_trends(train_data: pd.DataFrame) -> None:
    """Plot training-only target trends by purchase month."""

    monthly = train_data.groupby("purchase_period", observed=True).agg(
        late_rate=(CLASSIFICATION_TARGET, "mean"),
        mean_days=(REGRESSION_TARGET, "mean"),
        orders=(CLASSIFICATION_TARGET, "size"),
    )
    plt.figure(figsize=(11, 4))
    plt.plot(monthly.index, monthly["late_rate"] * 100, marker="o", color="#e76f51")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Late delivery rate (%)")
    plt.title("Training Late Delivery Rate by Purchase Month")
    save_figure("monthly_late_delivery_trend.png")

    plt.figure(figsize=(11, 4))
    plt.plot(monthly.index, monthly["mean_days"], marker="o", color="#2a9d8f")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Mean actual delivery days")
    plt.title("Training Delivery Duration by Purchase Month")
    save_figure("monthly_delivery_days_trend.png")


def plot_group_target_summary(train_data: pd.DataFrame, feature: str, filename: str, title: str) -> None:
    """Plot late rate and mean delivery days for a categorical group."""

    grouped = train_data.groupby(feature, observed=True).agg(
        orders=(CLASSIFICATION_TARGET, "size"),
        late_rate=(CLASSIFICATION_TARGET, "mean"),
        delivery_days=(REGRESSION_TARGET, "mean"),
    ).sort_values("orders", ascending=False).head(TOP_CATEGORIES)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].bar(grouped.index.astype(str), grouped["late_rate"] * 100, color="#e76f51")
    axes[0].set_title("Late rate (%)")
    axes[0].tick_params(axis="x", rotation=45)
    axes[1].bar(grouped.index.astype(str), grouped["delivery_days"], color="#2a9d8f")
    axes[1].set_title("Mean delivery days")
    axes[1].tick_params(axis="x", rotation=45)
    fig.suptitle(title)
    save_figure(filename)


def plot_numerical_distributions(train_data: pd.DataFrame) -> None:
    """Plot selected high-value numeric feature distributions on a log-friendly scale."""

    selected_features = [
        "promised_delivery_days",
        "seller_shipping_window_days",
        "total_item_price",
        "total_freight",
        "total_product_weight_g",
        "total_product_volume_cm3",
        "total_payment_value",
        "approval_delay_hours",
    ]
    fig, axes = plt.subplots(2, 4, figsize=(14, 7))
    for axis, feature in zip(axes.flat, selected_features, strict=True):
        values = train_data[feature].dropna()
        upper_bound = values.quantile(0.99)
        axis.hist(values.clip(upper=upper_bound), bins=35, color="#457b9d", edgecolor="white")
        axis.set_title(feature)
        axis.set_xlabel("Values clipped at p99")
    fig.suptitle("Training Numeric Feature Distributions")
    save_figure("numerical_feature_distributions.png")


def plot_correlation_heatmap(train_data: pd.DataFrame) -> None:
    """Plot a Spearman-correlation heatmap for numeric model inputs and targets."""

    columns = NUMERICAL_FEATURES + [CLASSIFICATION_TARGET, REGRESSION_TARGET]
    correlation = train_data[columns].corr(method="spearman")
    plt.figure(figsize=(16, 14))
    image = plt.imshow(correlation, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
    plt.colorbar(image, label="Spearman correlation")
    plt.xticks(range(len(columns)), columns, rotation=90, fontsize=7)
    plt.yticks(range(len(columns)), columns, fontsize=7)
    plt.title("Training Numeric Feature and Target Correlations")
    save_figure("feature_correlation_heatmap.png")


def write_summary(
    train_data: pd.DataFrame,
    missing_values: pd.DataFrame,
    numerical_summary: pd.DataFrame,
    drift_summary: pd.DataFrame,
    redundant_columns: pd.DataFrame,
) -> None:
    """Write concise, data-derived findings and explicit EDA scope to Markdown."""

    late_rate = train_data[CLASSIFICATION_TARGET].mean()
    target = train_data[REGRESSION_TARGET]
    highest_missing = missing_values.query("missing_count > 0").head(10)
    highest_drift = drift_summary.head(10)
    extreme_features = numerical_summary.sort_values("iqr_outlier_count", ascending=False).head(10)
    suspicious = numerical_summary[
        (numerical_summary["negative_count"] > 0)
        | (numerical_summary["minimum"] < 0)
    ]

    lines = [
        "# Training Data EDA Summary",
        "",
        "## Scope",
        "",
        f"- Training rows inspected: {len(train_data):,}.",
        "- Validation data was used only for feature-distribution drift; no validation target was read.",
        "- Test data was not loaded or inspected.",
        "- Outliers are reported, not removed.",
        "",
        "## Target Distribution",
        "",
        f"- Late-delivery rate: {late_rate:.2%} ({int(train_data[CLASSIFICATION_TARGET].sum()):,} late orders).",
        f"- Actual delivery days: mean {target.mean():.2f}, median {target.median():.2f}, p95 {target.quantile(0.95):.2f}, maximum {target.max():.2f}.",
        "",
        "## Highest Missingness",
        "",
    ]
    if highest_missing.empty:
        lines.append("- No missing values were found in the training dataset.")
    else:
        lines.extend(
            f"- `{row.column}`: {row.missing_count:,} ({row.missing_rate:.2%})"
            for row in highest_missing.itertuples()
        )

    lines.extend(["", "## Strongest Train-to-Validation Feature Drift", ""])
    lines.extend(
        f"- `{row.feature}` ({row.feature_type}): drift score {row.psi_or_tvd:.4f}, validation unseen rate {row.validation_unseen_rate:.2%}"
        for row in highest_drift.itertuples()
    )

    lines.extend(["", "## Extreme Values", ""])
    lines.extend(
        f"- `{row.column}`: {row.iqr_outlier_count:,} IQR-rule outliers; skewness {row.skewness:.2f}"
        for row in extreme_features.itertuples()
    )

    lines.extend(["", "## Suspicious or Impossible Values", ""])
    if suspicious.empty:
        lines.append("- No numeric input feature has a negative value; verify domain-specific bounds before modelling.")
    else:
        lines.extend(
            f"- `{row.column}`: minimum {row.minimum:.4f}; negative values {row.negative_count:,}"
            for row in suspicious.itertuples()
        )

    lines.extend(["", "## Redundancy", ""])
    if redundant_columns.empty:
        lines.append("- No exact duplicate columns or numeric pairs with absolute Spearman correlation >= 0.95 were found.")
    else:
        lines.append(
            f"- {len(redundant_columns):,} potential redundant feature relationships are listed in `redundant_columns.csv`."
        )

    lines.extend(
        [
            "",
            "## Next-Step Guardrails",
            "",
            "- Fit all learned transformations and route frequencies on training data only.",
            "- Preserve the 47-feature API contract; generate derived features internally.",
            "- Do not select features, tune models, or tune thresholds from test data.",
            "",
        ]
    )
    SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """Run the full Phase 1 EDA workflow."""

    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    train_data = prepare_derived_features(load_split(TRAIN_PATH))
    validation_data = pd.read_parquet(
        VALIDATION_PATH,
        columns=MODEL_FEATURES,
    )

    missing_values = create_missing_value_report(train_data)
    numerical_summary = create_numerical_summary(train_data)
    create_categorical_summary(train_data)
    create_feature_target_summary(train_data)
    drift_summary = create_drift_summary(train_data, validation_data)
    redundant_columns = create_redundant_column_report(train_data)

    plot_target_distributions(train_data)
    plot_monthly_trends(train_data)
    plot_group_target_summary(train_data, "delivery_scope", "delivery_scope_targets.png", "Same-State and Cross-State Delivery")
    plot_group_target_summary(train_data, "multi_item_group", "multi_item_targets.png", "Single-Item and Multi-Item Orders")
    plot_group_target_summary(train_data, "multi_seller_group", "multi_seller_targets.png", "Single-Seller and Multi-Seller Orders")
    plot_group_target_summary(train_data, "primary_payment_type", "payment_method_targets.png", "Payment Method Outcomes")
    plot_group_target_summary(train_data, "customer_state", "customer_state_targets.png", "Customer State Outcomes")
    plot_group_target_summary(train_data, "primary_seller_state", "seller_state_targets.png", "Seller State Outcomes")
    plot_group_target_summary(train_data, "seller_customer_route", "route_targets.png", "Top Seller-to-Customer Routes")
    plot_numerical_distributions(train_data)
    plot_correlation_heatmap(train_data)
    write_summary(
        train_data,
        missing_values,
        numerical_summary,
        drift_summary,
        redundant_columns,
    )

    print(f"EDA completed for {len(train_data):,} training rows.")
    print(f"Reports saved under: {REPORT_DIRECTORY}")


if __name__ == "__main__":
    main()