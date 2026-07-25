"""Regression model definitions."""

from __future__ import annotations

from sklearn.base import RegressorMixin
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor


def get_regression_models() -> dict[str, RegressorMixin]:
    """Return regression models for validation comparison."""

    return {
        "dummy_regressor": DummyRegressor(
            strategy="median",
        ),

        "linear_regression": LinearRegression(),

        "decision_tree_regressor": DecisionTreeRegressor(
            max_depth=15,
            min_samples_leaf=20,
            random_state=42,
        ),

        "random_forest_regressor": RandomForestRegressor(
            n_estimators=200,
            max_depth=20,
            min_samples_leaf=5,
            max_features=0.8,
            n_jobs=-1,
            random_state=42,
        ),
    }