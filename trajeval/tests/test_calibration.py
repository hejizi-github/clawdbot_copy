"""Tests for the calibration module."""

from __future__ import annotations

import json

import pytest

from trajeval.calibration import (
    AnnotationStore,
    HumanAnnotation,
    compute_correlation,
)
from trajeval.scorer import JudgeDimension, JudgeResult


def _ann(tid, dim, score, annotator="alice"):
    return HumanAnnotation(
        trace_id=tid, dimension=dim,
        human_score=score, annotator=annotator,
    )


def _jr(tid, dim, score, overall):
    return JudgeResult(
        trace_id=tid,
        dimensions=[JudgeDimension(name=dim, score=score)],
        overall_score=overall,
    )


@pytest.fixture
def tmp_annotations(tmp_path):
    return tmp_path / "annotations.jsonl"


@pytest.fixture
def sample_annotations():
    return [
        _ann("t1", "task_completion", 5),
        _ann("t2", "task_completion", 4),
        _ann("t3", "task_completion", 2),
        _ann("t4", "task_completion", 1),
        _ann("t5", "task_completion", 3),
    ]


@pytest.fixture
def matching_judge_results():
    """Judge results that correlate well with sample_annotations."""
    return [
        _jr("t1", "task_completion", 5, 1.0),
        _jr("t2", "task_completion", 4, 0.8),
        _jr("t3", "task_completion", 2, 0.4),
        _jr("t4", "task_completion", 1, 0.2),
        _jr("t5", "task_completion", 3, 0.6),
    ]


@pytest.fixture
def uncorrelated_judge_results():
    """Judge results that do NOT correlate with sample_annotations."""
    return [
        _jr("t1", "task_completion", 1, 0.2),
        _jr("t2", "task_completion", 5, 1.0),
        _jr("t3", "task_completion", 4, 0.8),
        _jr("t4", "task_completion", 3, 0.6),
        _jr("t5", "task_completion", 2, 0.4),
    ]


class TestAnnotationStore:
    def test_save_and_load_roundtrip(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        ann = _ann("t1", "task_completion", 4)
        store.save(ann)

        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].trace_id == "t1"
        assert loaded[0].dimension == "task_completion"
        assert loaded[0].human_score == 4

    def test_save_batch(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        anns = [
            _ann("t1", "task_completion", 5),
            _ann("t1", "reasoning_quality", 3),
        ]
        store.save_batch(anns)

        loaded = store.load()
        assert len(loaded) == 2
        assert loaded[0].human_score == 5
        assert loaded[1].human_score == 3

    def test_append_preserves_existing(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        store.save(_ann("t1", "task_completion", 4))
        store.save(_ann("t2", "task_completion", 2))

        loaded = store.load()
        assert len(loaded) == 2

    def test_load_empty_file(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        loaded = store.load()
        assert loaded == []

    def test_load_for_trace(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        store.save_batch([
            _ann("t1", "task_completion", 5),
            _ann("t2", "task_completion", 3),
            _ann("t1", "reasoning_quality", 4),
        ])

        t1_anns = store.load_for_trace("t1")
        assert len(t1_anns) == 2
        assert all(a.trace_id == "t1" for a in t1_anns)

    def test_jsonl_format(self, tmp_annotations):
        store = AnnotationStore(tmp_annotations)
        store.save(_ann("t1", "task_completion", 4))

        raw = tmp_annotations.read_text()
        data = json.loads(raw.strip())
        assert data["trace_id"] == "t1"
        assert data["human_score"] == 4


class TestComputeCorrelation:
    def test_perfect_correlation(
        self, sample_annotations, matching_judge_results,
    ):
        result = compute_correlation(
            sample_annotations, matching_judge_results,
        )
        assert result.overall_spearman_rho == 1.0
        assert result.overall_p_value < 0.05
        assert result.total_pairs == 5

    def test_weak_correlation(
        self, sample_annotations, uncorrelated_judge_results,
    ):
        result = compute_correlation(
            sample_annotations, uncorrelated_judge_results,
        )
        assert result.overall_spearman_rho < 0.5

    def test_per_dimension_results(
        self, sample_annotations, matching_judge_results,
    ):
        result = compute_correlation(
            sample_annotations, matching_judge_results,
        )
        assert len(result.dimensions) == 1
        assert result.dimensions[0].dimension == "task_completion"
        assert result.dimensions[0].sample_size == 5

    def test_no_matching_pairs(self):
        annotations = [_ann("t1", "task_completion", 5)]
        judge_results = [_jr("t99", "task_completion", 5, 1.0)]
        result = compute_correlation(annotations, judge_results)
        assert result.total_pairs == 0
        assert result.overall_spearman_rho == 0.0

    def test_too_few_pairs_warning(self):
        annotations = [
            _ann("t1", "task_completion", 5),
            _ann("t2", "task_completion", 3),
        ]
        judge_results = [
            _jr("t1", "task_completion", 5, 1.0),
            _jr("t2", "task_completion", 3, 0.6),
        ]
        result = compute_correlation(annotations, judge_results)
        assert any("at least 3" in w for w in result.warnings)

    def test_constant_scores_warning(self):
        annotations = [
            _ann(f"t{i}", "task_completion", 5)
            for i in range(5)
        ]
        judge_results = [
            _jr(f"t{i}", "task_completion", 5, 1.0)
            for i in range(5)
        ]
        result = compute_correlation(annotations, judge_results)
        assert any("constant" in w for w in result.warnings)

    def test_multi_dimension(self):
        annotations = [
            _ann("t1", "task_completion", 5),
            _ann("t2", "task_completion", 3),
            _ann("t3", "task_completion", 1),
            _ann("t1", "reasoning_quality", 4),
            _ann("t2", "reasoning_quality", 2),
            _ann("t3", "reasoning_quality", 5),
        ]
        tc = JudgeDimension(name="task_completion", score=5)
        rq = JudgeDimension(name="reasoning_quality", score=4)
        judge_results = [
            JudgeResult(
                trace_id="t1",
                dimensions=[tc, rq],
                overall_score=0.9,
            ),
            JudgeResult(
                trace_id="t2",
                dimensions=[
                    JudgeDimension(name="task_completion", score=3),
                    JudgeDimension(name="reasoning_quality", score=2),
                ],
                overall_score=0.5,
            ),
            JudgeResult(
                trace_id="t3",
                dimensions=[
                    JudgeDimension(name="task_completion", score=1),
                    JudgeDimension(name="reasoning_quality", score=5),
                ],
                overall_score=0.6,
            ),
        ]
        result = compute_correlation(annotations, judge_results)
        assert len(result.dimensions) == 2
        assert result.total_pairs == 6

    def test_empty_inputs(self):
        result = compute_correlation([], [])
        assert result.total_pairs == 0
        assert result.dimensions == []


class TestAnnotationValidation:
    def test_score_out_of_range_high(self):
        with pytest.raises(Exception):
            _ann("t1", "task_completion", 6)

    def test_score_out_of_range_low(self):
        with pytest.raises(Exception):
            _ann("t1", "task_completion", -1)

    def test_valid_range_boundaries(self):
        a0 = _ann("t1", "task_completion", 0)
        a5 = _ann("t1", "task_completion", 5)
        assert a0.human_score == 0
        assert a5.human_score == 5

    def test_annotator_default(self):
        ann = HumanAnnotation(
            trace_id="t1", dimension="task_completion",
            human_score=3,
        )
        assert ann.annotator == "default"

    def test_timestamp_auto_set(self):
        ann = HumanAnnotation(
            trace_id="t1", dimension="task_completion",
            human_score=3,
        )
        assert ann.timestamp
