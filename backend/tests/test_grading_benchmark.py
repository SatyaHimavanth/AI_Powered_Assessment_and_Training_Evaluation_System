import pytest

from tools.grading_benchmark import evaluate


def test_grading_benchmark_reports_score_and_dimension_agreement():
    result = evaluate([
        {"human_score": 0.8, "model_score": 0.75,
         "human_dimensions": {"accuracy": 0.9}, "model_dimensions": {"accuracy": 0.85}},
        {"human_score": 0.4, "model_score": 0.6,
         "human_dimensions": {"accuracy": 0.3}, "model_dimensions": {"accuracy": 0.5}},
    ], tolerance=0.1)
    assert result == {
        "sample_count": 2, "mae": 0.125, "within_tolerance_rate": 0.5,
        "dimension_agreement_rate": 0.5, "tolerance": 0.1,
    }


def test_grading_benchmark_requires_real_labels_and_valid_ranges():
    with pytest.raises(ValueError, match="at least one"):
        evaluate([])
    with pytest.raises(ValueError, match="normalized"):
        evaluate([{"human_score": 2, "model_score": 0.5}])
