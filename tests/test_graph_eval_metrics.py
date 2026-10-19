"""
Unit test for graph accuracy metrics calculation and Wilson 95% CI on a synthetic 20-row fixture.
"""
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_GRAPH = REPO_ROOT / "eval" / "graph"
if str(EVAL_GRAPH) not in sys.path:
    sys.path.insert(0, str(EVAL_GRAPH))

from metrics import wilson_ci, calculate_metrics


def test_wilson_ci_bounds_and_values():
    low, high = wilson_ci(10, 10)
    assert 0.65 < low < 1.0
    assert high == 1.0

    low_zero, high_zero = wilson_ci(0, 10)
    assert low_zero == 0.0
    assert 0.0 < high_zero < 0.35

    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_calculate_metrics_unvalidated_when_blank():
    rows = [
        {"repo": "test/repo", "sha": "123", "edge_type": "calls", "label": ""}
        for _ in range(15)
    ]
    res = calculate_metrics(rows)
    assert res["validated"] is False
    assert res["status"] == "NOT VALIDATED: 0 of 15 labels reviewed"
    assert res["reviewed_count"] == 0


def test_calculate_metrics_synthetic_20_row_fixture():
    # 20 synthetic rows:
    # calls: 6 rows (4 TP, 1 FP, 1 AMBIGUOUS) -> precision 4/5 = 0.8
    # imports: 8 rows (7 TP, 1 FP)            -> precision 7/8 = 0.875
    # contains: 6 rows (3 TP, 2 FP, 1 AMBIGUOUS) -> precision 3/5 = 0.6
    # Total: 14 TP, 4 FP, 2 AMBIGUOUS
    rows = []
    # calls
    for _ in range(4):
        rows.append({"edge_type": "calls", "label": "TP"})
    rows.append({"edge_type": "calls", "label": "FP"})
    rows.append({"edge_type": "calls", "label": "AMBIGUOUS"})

    # imports
    for _ in range(7):
        rows.append({"edge_type": "imports", "label": "TP"})
    rows.append({"edge_type": "imports", "label": "FP"})

    # contains
    for _ in range(3):
        rows.append({"edge_type": "contains", "label": "TP"})
    for _ in range(2):
        rows.append({"edge_type": "contains", "label": "FP"})
    rows.append({"edge_type": "contains", "label": "AMBIGUOUS"})

    assert len(rows) == 20

    res = calculate_metrics(rows)
    assert res["validated"] is True
    assert res["reviewed_count"] == 20
    assert res["status"] == "VALIDATED: 20 of 20 labels reviewed"

    ov = res["overall"]
    assert ov["tp"] == 14
    assert ov["fp"] == 4
    assert ov["ambiguous"] == 2
    assert ov["evaluated_count"] == 18
    assert ov["precision"] == round(14 / 18, 4)
    assert 0.5 < ov["precision_95ci"][0] < ov["precision"]
    assert ov["precision"] < ov["precision_95ci"][1] < 1.0

    # Per edge type checks
    calls = res["per_edge_type"]["calls"]
    assert calls["tp"] == 4
    assert calls["fp"] == 1
    assert calls["ambiguous"] == 1
    assert calls["precision"] == 0.8

    imports = res["per_edge_type"]["imports"]
    assert imports["tp"] == 7
    assert imports["fp"] == 1
    assert imports["precision"] == 0.875

    contains = res["per_edge_type"]["contains"]
    assert contains["tp"] == 3
    assert contains["fp"] == 2
    assert contains["precision"] == 0.6
