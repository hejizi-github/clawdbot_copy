"""Calibration module: human annotations and LLM-judge correlation analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field
from scipy.stats import spearmanr

from .scorer import JudgeResult


class HumanAnnotation(BaseModel):
    trace_id: str
    dimension: str
    human_score: int = Field(ge=0, le=5)
    annotator: str = "default"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class DimensionCorrelation(BaseModel):
    dimension: str
    spearman_rho: float
    p_value: float
    sample_size: int


class CalibrationResult(BaseModel):
    overall_spearman_rho: float = 0.0
    overall_p_value: float = 1.0
    total_pairs: int = 0
    dimensions: list[DimensionCorrelation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnnotationStore:
    """Append-only JSONL storage for human annotations."""

    def __init__(self, path: Path):
        self.path = path

    def save(self, annotation: HumanAnnotation) -> None:
        with open(self.path, "a") as f:
            f.write(annotation.model_dump_json() + "\n")

    def save_batch(self, annotations: list[HumanAnnotation]) -> None:
        with open(self.path, "a") as f:
            for a in annotations:
                f.write(a.model_dump_json() + "\n")

    def load(self) -> list[HumanAnnotation]:
        if not self.path.exists():
            return []
        annotations = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    annotations.append(HumanAnnotation.model_validate_json(line))
        return annotations

    def load_for_trace(self, trace_id: str) -> list[HumanAnnotation]:
        return [a for a in self.load() if a.trace_id == trace_id]


def load_judge_results(path: Path) -> list[JudgeResult]:
    """Load judge results from a JSONL file."""
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            results.append(JudgeResult.model_validate(data))
    return results


def compute_correlation(
    annotations: list[HumanAnnotation],
    judge_results: list[JudgeResult],
) -> CalibrationResult:
    """Compute Spearman rank correlation between human and LLM-judge scores."""
    judge_lookup: dict[tuple[str, str], int] = {}
    for jr in judge_results:
        for dim in jr.dimensions:
            judge_lookup[(jr.trace_id, dim.name)] = dim.score

    paired: dict[str, list[tuple[int, int]]] = {}
    for ann in annotations:
        key = (ann.trace_id, ann.dimension)
        if key in judge_lookup:
            paired.setdefault(ann.dimension, []).append(
                (ann.human_score, judge_lookup[key])
            )

    warnings: list[str] = []
    dim_results: list[DimensionCorrelation] = []
    all_human: list[int] = []
    all_judge: list[int] = []

    for dim_name, pairs in sorted(paired.items()):
        human_scores = [p[0] for p in pairs]
        judge_scores = [p[1] for p in pairs]

        if len(pairs) < 3:
            warnings.append(
                f"{dim_name}: only {len(pairs)} pairs — need at least 3 for correlation"
            )
            continue

        if len(pairs) < 10:
            warnings.append(
                f"{dim_name}: {len(pairs)} pairs — results may not be reliable (recommend 10+)"
            )

        if len(set(human_scores)) == 1 or len(set(judge_scores)) == 1:
            warnings.append(f"{dim_name}: constant scores — cannot compute correlation")
            dim_results.append(DimensionCorrelation(
                dimension=dim_name, spearman_rho=0.0, p_value=1.0, sample_size=len(pairs),
            ))
            continue

        rho, pval = spearmanr(human_scores, judge_scores)
        dim_results.append(DimensionCorrelation(
            dimension=dim_name,
            spearman_rho=round(float(rho), 4),
            p_value=round(float(pval), 6),
            sample_size=len(pairs),
        ))
        all_human.extend(human_scores)
        all_judge.extend(judge_scores)

    overall_rho = 0.0
    overall_p = 1.0
    total_pairs = len(all_human)

    if total_pairs >= 3 and len(set(all_human)) > 1 and len(set(all_judge)) > 1:
        rho, pval = spearmanr(all_human, all_judge)
        overall_rho = round(float(rho), 4)
        overall_p = round(float(pval), 6)

    if total_pairs < 10:
        warnings.append(
            f"Overall: {total_pairs} total pairs — recommend 10+ for reliable calibration"
        )

    return CalibrationResult(
        overall_spearman_rho=overall_rho,
        overall_p_value=overall_p,
        total_pairs=total_pairs,
        dimensions=dim_results,
        warnings=warnings,
    )
