from __future__ import annotations

import random
from typing import Any

SEED = 20261121
SEARCH_CONFIGURATIONS = 60


def model_factory(algorithm=None, params=None, pos_weight=None, space="extended"):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    params = params or {}
    lr = Pipeline([("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                   ("scale", StandardScaler()),
                   ("model", LogisticRegression(max_iter=2000,
                    class_weight="balanced", solver=params.get("solver", "liblinear"),
                    penalty=params.get("penalty", "l2"), C=params.get("C", 1.0)))])
    rf = RandomForestClassifier(n_estimators=params.get("n_estimators", 150),
                                class_weight="balanced", random_state=SEED, n_jobs=1,
                                max_depth=params.get("max_depth"),
                                min_samples_leaf=params.get("min_samples_leaf", 1),
                                max_features=params.get("max_features", "sqrt"),
                                oob_score=True, bootstrap=True)
    if space == "table35":
        xgb = XGBClassifier(n_estimators=params.get("n_estimators", 100),
                            max_depth=params.get("max_depth", 3),
                            learning_rate=params.get("learning_rate", .1),
                            subsample=params.get("subsample", 1.0),
                            colsample_bytree=params.get("colsample_bytree", 1.0),
                            reg_lambda=params.get("reg_lambda", 1.0),
                            scale_pos_weight=pos_weight or 1.0,
                            random_state=SEED, n_jobs=1, verbosity=0)
    else:
        xgb = XGBClassifier(n_estimators=params.get("n_estimators", 100),
                            max_depth=params.get("max_depth", 3),
                            learning_rate=params.get("learning_rate", .05),
                            min_child_weight=params.get("min_child_weight", 1),
                            subsample=params.get("subsample", .8),
                            colsample_bytree=params.get("colsample_bytree", .8),
                            eval_metric="logloss",
                            scale_pos_weight=pos_weight or 1.0,
                            random_state=SEED, n_jobs=1, verbosity=0)
    models: dict[str, Any] = {"LR": lr, "RF": rf, "XGB": xgb}
    return models if algorithm is None else models[algorithm]


def _search_configs(name: str, space: str = "extended") -> list[dict[str, Any]]:
    if space not in {"table35", "extended"}:
        raise ValueError(f"unknown search space: {space}")
    rng = random.Random(SEED + sum(ord(char) for char in name))
    if space == "table35" and name == "LR":
        return [{"penalty": penalty, "solver": "liblinear", "C": c}
                for penalty in ("l1", "l2") for c in (0.01, 0.1, 1, 10, 100)]
    if space == "table35" and name == "RF":
        values = {"max_depth": [None, 5, 10, 15, 20],
                  "min_samples_leaf": [1, 2, 5, 10],
                  "max_features": ["sqrt", "log2", 0.5]}
    elif space == "table35":
        values = {"n_estimators": [100, 300, 500],
                  "max_depth": [3, 4, 5, 6, 8],
                  "learning_rate": [.01, .05, .1, .2],
                  "subsample": [.7, .8, .9, 1.0],
                  "colsample_bytree": [.7, .8, .9, 1.0],
                  "reg_lambda": [.1, 1, 5, 10]}
    elif name == "LR":
        values = {"penalty": ["l1", "l2"], "solver": ["liblinear"],
                  "C": [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100]}
    elif name == "RF":
        values = {"max_depth": [None, 3, 5, 8, 12, 20],
                  "min_samples_leaf": [1, 2, 4, 8, 12],
                  "max_features": ["sqrt", "log2", 0.5, 1.0]}
    else:
        values = {"n_estimators": [100], "max_depth": [2, 3, 4, 5],
                  "learning_rate": [.02, .05, .1, .2],
                  "min_child_weight": [1, 3, 6], "subsample": [.7, .85, 1.0],
                  "colsample_bytree": [.7, .85, 1.0]}
    configs = []
    for _ in range(SEARCH_CONFIGURATIONS):
        configs.append({key: rng.choice(options) for key, options in values.items()})
    return configs
