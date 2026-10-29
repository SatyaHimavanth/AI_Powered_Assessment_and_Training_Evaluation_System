"""Score a human-labelled grading benchmark JSONL file without calling an LLM.

Each row: {"item_id": ..., "human_score": 0..1, "model_score": 0..1,
"human_dimensions": {"accuracy": 0..1}, "model_dimensions": {...}}.
Never put candidate names, contact details, or other direct identifiers here.
"""
import argparse
import json
from pathlib import Path
import statistics


def evaluate(rows: list[dict], tolerance: float = 0.1) -> dict:
    if not rows:
        raise ValueError("Benchmark must contain at least one human-labelled row")
    errors: list[float] = []
    agreements = 0
    dimension_matches = total_dimensions = 0
    for number, row in enumerate(rows, 1):
        human = float(row["human_score"])
        predicted = float(row["model_score"])
        if not 0 <= human <= 1 or not 0 <= predicted <= 1:
            raise ValueError(f"Row {number}: scores must be normalized to [0,1]")
        errors.append(abs(human - predicted))
        agreements += abs(human - predicted) <= tolerance
        expected_dims = row.get("human_dimensions", {})
        actual_dims = row.get("model_dimensions", {})
        for key, expected in expected_dims.items():
            if key in actual_dims:
                total_dimensions += 1
                dimension_matches += int(abs(float(expected) - float(actual_dims[key])) <= tolerance)
    return {
        "sample_count": len(rows),
        "mae": round(statistics.mean(errors), 4),
        "within_tolerance_rate": round(agreements / len(rows), 4),
        "dimension_agreement_rate": round(dimension_matches / total_dimensions, 4) if total_dimensions else None,
        "tolerance": tolerance,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--tolerance", type=float, default=0.1)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(evaluate(rows, args.tolerance), indent=2))


if __name__ == "__main__":
    main()
