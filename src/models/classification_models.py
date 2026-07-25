"""Classification model definitions."""

from __future__ import annotations

from sklearn.base import ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier


def get_classification_models() -> dict[str, ClassifierMixin]:
    """Return classification models for baseline comparison."""

    return {
        "dummy_classifier": DummyClassifier(
            strategy="prior",
        ),

        "logistic_regression": LogisticRegression(
            class_weight="balanced",
            max_iter=2000,
            random_state=42,
        ),

        "decision_tree": DecisionTreeClassifier(
            max_depth=12,
            min_samples_leaf=20,
            class_weight="balanced",
            random_state=42,
        ),

        "random_forest": RandomForestClassifier(
            n_estimators=250,
            max_depth=18,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        ),
    }