"""Training-reference feature, score, and locked-decision distribution baselines."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from modelguard.core.hashing import HashRecord
from modelguard.core.serialization import StrictArtifactModel
from modelguard.data.schema import (
    CATEGORICAL_FEATURES,
    FEATURE_ORDER,
    NUMERIC_FEATURES,
    canonical_feature_definitions,
)
from modelguard.data.split import membership_hash
from modelguard.training.config import BaselineConfig
from modelguard.training.evaluate import MetricValue, ThresholdContract, safe_ratio

RiskLevel = Literal["low_risk", "high_risk"]


class MissingnessProfile(StrictArtifactModel):
    count: int = Field(ge=0)
    proportion: MetricValue


class NumericBin(StrictArtifactModel):
    semantic: Literal["underflow", "interval", "constant_reference", "overflow"]
    lower_bound: float | None
    upper_bound: float | None
    lower_inclusive: bool
    upper_inclusive: bool
    count: int = Field(ge=0)
    proportion: MetricValue

    @model_validator(mode="after")
    def validate_semantics(self) -> NumericBin:
        if self.semantic == "underflow":
            if self.lower_bound is not None or self.upper_bound is None:
                raise ValueError("underflow bins require only a finite upper bound")
        elif self.semantic == "overflow":
            if self.lower_bound is None or self.upper_bound is not None:
                raise ValueError("overflow bins require only a finite lower bound")
        elif self.lower_bound is None or self.upper_bound is None:
            raise ValueError("reference bins require finite bounds")
        return self


class NumericFeatureProfile(StrictArtifactModel):
    constant: bool
    row_count: int = Field(gt=0)
    finite_count: int = Field(ge=0)
    missingness: MissingnessProfile
    requested_quantiles: list[float]
    quantile_method: Literal["linear"]
    collapsed_reference_edges: list[float]
    bins: list[NumericBin]

    @model_validator(mode="after")
    def validate_counts(self) -> NumericFeatureProfile:
        if self.finite_count + self.missingness.count != self.row_count:
            raise ValueError("numeric finite and missing counts must reconcile")
        if sum(item.count for item in self.bins) != self.finite_count:
            raise ValueError("numeric bin counts must reconcile to finite count")
        if self.constant != (len(self.collapsed_reference_edges) == 1):
            raise ValueError("constant flag must match collapsed quantile edges")
        return self


class CategoricalFeatureProfile(StrictArtifactModel):
    constant: bool
    row_count: int = Field(gt=0)
    universe: list[str]
    counts: dict[str, int]
    proportions: dict[str, MetricValue]
    missingness: MissingnessProfile

    @model_validator(mode="after")
    def validate_counts(self) -> CategoricalFeatureProfile:
        if set(self.counts) != set(self.universe) or set(self.proportions) != set(self.universe):
            raise ValueError("categorical counts and proportions must cover the exact universe")
        if sum(self.counts.values()) != self.row_count:
            raise ValueError("categorical bucket counts must reconcile to row count")
        return self


class ScoreBin(StrictArtifactModel):
    index: int = Field(ge=0, le=9)
    interval: str
    lower_bound: float
    upper_bound: float
    upper_inclusive: bool
    count: int = Field(ge=0)
    proportion: MetricValue


class ScoreDistribution(StrictArtifactModel):
    binning: Literal["fixed_deciles_[0,1]"] = "fixed_deciles_[0,1]"
    bins: list[ScoreBin]


class DecisionDistribution(StrictArtifactModel):
    comparison: Literal["score >= threshold"]
    threshold: float = Field(ge=0.0, le=1.0)
    counts: dict[RiskLevel, int]
    proportions: dict[RiskLevel, MetricValue]


class BaselineProfile(StrictArtifactModel):
    """Training distribution reference with no training-performance evidence."""

    contract_version: Literal["modelguard.baseline-profile.v1"] = "modelguard.baseline-profile.v1"
    model_version: str
    created_at: str
    reference_scope: Literal["training_distribution_only_not_performance"] = (
        "training_distribution_only_not_performance"
    )
    training_row_count: int = Field(gt=0)
    training_membership_hash: HashRecord
    feature_order: list[str]
    numeric_features: dict[str, NumericFeatureProfile]
    categorical_features: dict[str, CategoricalFeatureProfile]
    calibrated_score_distribution: ScoreDistribution
    locked_decision_distribution: DecisionDistribution

    @model_validator(mode="after")
    def validate_profile(self) -> BaselineProfile:
        if self.feature_order != list(FEATURE_ORDER):
            raise ValueError("baseline feature order must match the model allowlist")
        if set(self.numeric_features) != set(NUMERIC_FEATURES):
            raise ValueError("numeric baseline must cover the locked feature set")
        if set(self.categorical_features) != set(CATEGORICAL_FEATURES):
            raise ValueError("categorical baseline must cover the locked feature set")
        score_count = sum(item.count for item in self.calibrated_score_distribution.bins)
        if score_count != self.training_row_count:
            raise ValueError("score baseline counts must reconcile to training row count")
        if sum(self.locked_decision_distribution.counts.values()) != self.training_row_count:
            raise ValueError("decision baseline counts must reconcile to training row count")
        return self


def _numeric_profile(series: pd.Series, config: BaselineConfig) -> NumericFeatureProfile:
    row_count = len(series)
    missing_count = int(series.isna().sum())
    finite_values = pd.to_numeric(series.dropna(), errors="raise").to_numpy(dtype=float)
    if not np.isfinite(finite_values).all():
        raise ValueError("numeric baseline values must be finite")
    if len(finite_values) == 0:
        raise ValueError("numeric baseline requires at least one finite training value")
    quantile_values = np.quantile(
        finite_values,
        config.numeric_quantiles,
        method=config.numeric_quantile_method,
    )
    edges = sorted({float(value) for value in quantile_values})
    finite_count = len(finite_values)
    bins: list[NumericBin] = []
    reference_min = edges[0]
    reference_max = edges[-1]
    underflow_count = int((finite_values < reference_min).sum())
    bins.append(
        NumericBin(
            semantic="underflow",
            lower_bound=None,
            upper_bound=reference_min,
            lower_inclusive=False,
            upper_inclusive=False,
            count=underflow_count,
            proportion=safe_ratio(underflow_count, finite_count, zero_reason="no_finite_values"),
        )
    )
    if len(edges) == 1:
        constant_count = int((finite_values == reference_min).sum())
        bins.append(
            NumericBin(
                semantic="constant_reference",
                lower_bound=reference_min,
                upper_bound=reference_min,
                lower_inclusive=True,
                upper_inclusive=True,
                count=constant_count,
                proportion=safe_ratio(constant_count, finite_count, zero_reason="no_finite_values"),
            )
        )
    else:
        for index, (lower, upper) in enumerate(pairwise(edges)):
            is_last = index == len(edges) - 2
            if is_last:
                mask = (finite_values >= lower) & (finite_values <= upper)
            else:
                mask = (finite_values >= lower) & (finite_values < upper)
            count = int(mask.sum())
            bins.append(
                NumericBin(
                    semantic="interval",
                    lower_bound=lower,
                    upper_bound=upper,
                    lower_inclusive=True,
                    upper_inclusive=is_last,
                    count=count,
                    proportion=safe_ratio(count, finite_count, zero_reason="no_finite_values"),
                )
            )
    overflow_count = int((finite_values > reference_max).sum())
    bins.append(
        NumericBin(
            semantic="overflow",
            lower_bound=reference_max,
            upper_bound=None,
            lower_inclusive=False,
            upper_inclusive=False,
            count=overflow_count,
            proportion=safe_ratio(overflow_count, finite_count, zero_reason="no_finite_values"),
        )
    )
    return NumericFeatureProfile(
        constant=len(edges) == 1,
        row_count=row_count,
        finite_count=finite_count,
        missingness=MissingnessProfile(
            count=missing_count,
            proportion=safe_ratio(missing_count, row_count, zero_reason="empty_reference"),
        ),
        requested_quantiles=config.numeric_quantiles,
        quantile_method=config.numeric_quantile_method,
        collapsed_reference_edges=edges,
        bins=bins,
    )


def _categorical_profile(
    series: pd.Series,
    known_categories: list[str],
    config: BaselineConfig,
) -> CategoricalFeatureProfile:
    universe = [*known_categories, config.other_bucket, config.missing_bucket]
    counts = dict.fromkeys(universe, 0)
    for value in series:
        bucket: str
        if pd.isna(value):
            bucket = config.missing_bucket
        elif str(value) in known_categories:
            bucket = str(value)
        else:
            bucket = config.other_bucket
        counts[bucket] += 1
    row_count = len(series)
    proportions = {
        bucket: safe_ratio(count, row_count, zero_reason="empty_reference")
        for bucket, count in counts.items()
    }
    nonzero_categories = sum(count > 0 for count in counts.values())
    missing_count = counts[config.missing_bucket]
    return CategoricalFeatureProfile(
        constant=nonzero_categories == 1,
        row_count=row_count,
        universe=universe,
        counts=counts,
        proportions=proportions,
        missingness=MissingnessProfile(
            count=missing_count,
            proportion=safe_ratio(missing_count, row_count, zero_reason="empty_reference"),
        ),
    )


def _score_distribution(scores: np.ndarray) -> ScoreDistribution:
    bins: list[ScoreBin] = []
    row_count = len(scores)
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        is_last = index == 9
        mask = (scores >= lower) & (scores <= upper if is_last else scores < upper)
        count = int(mask.sum())
        right_bracket = "]" if is_last else ")"
        bins.append(
            ScoreBin(
                index=index,
                interval=f"[{lower:.1f},{upper:.1f}{right_bracket}",
                lower_bound=lower,
                upper_bound=upper,
                upper_inclusive=is_last,
                count=count,
                proportion=safe_ratio(count, row_count, zero_reason="empty_reference"),
            )
        )
    return ScoreDistribution(bins=bins)


def build_baseline_profile(
    training_features: pd.DataFrame,
    training_scores: np.ndarray,
    threshold: ThresholdContract,
    config: BaselineConfig,
    *,
    model_version: str,
    created_at: str,
) -> BaselineProfile:
    """Freeze train-only input and deployed-output distributions after threshold lock."""

    if list(training_features.columns) != list(FEATURE_ORDER):
        raise ValueError("baseline requires the exact model feature order")
    scores = np.asarray(training_scores, dtype=float)
    if len(scores) != len(training_features) or len(scores) == 0:
        raise ValueError("training scores must be non-empty and aligned to training features")
    if not np.isfinite(scores).all() or ((scores < 0.0) | (scores > 1.0)).any():
        raise ValueError("training reference scores must be finite and in [0, 1]")
    definitions = {item.name: item for item in canonical_feature_definitions()}
    numeric_profiles = {
        feature: _numeric_profile(training_features[feature], config)
        for feature in NUMERIC_FEATURES
    }
    categorical_profiles: dict[str, CategoricalFeatureProfile] = {}
    for feature in CATEGORICAL_FEATURES:
        categories = definitions[feature].categories
        if categories is None:
            raise RuntimeError(f"internal categorical schema is missing a domain for {feature}")
        categorical_profiles[feature] = _categorical_profile(
            training_features[feature], categories, config
        )
    high_risk_count = int((scores >= threshold.threshold).sum())
    low_risk_count = len(scores) - high_risk_count
    decision_counts: dict[RiskLevel, int] = {
        "low_risk": low_risk_count,
        "high_risk": high_risk_count,
    }
    return BaselineProfile(
        model_version=model_version,
        created_at=created_at,
        training_row_count=len(training_features),
        training_membership_hash=membership_hash(training_features.index.astype(str).tolist()),
        feature_order=list(FEATURE_ORDER),
        numeric_features=numeric_profiles,
        categorical_features=categorical_profiles,
        calibrated_score_distribution=_score_distribution(scores),
        locked_decision_distribution=DecisionDistribution(
            comparison=threshold.comparison,
            threshold=threshold.threshold,
            counts=decision_counts,
            proportions={
                key: safe_ratio(value, len(scores), zero_reason="empty_reference")
                for key, value in decision_counts.items()
            },
        ),
    )
