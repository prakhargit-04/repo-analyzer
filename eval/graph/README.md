# Graph Accuracy Evaluation Harness

> **Status: HARNESS BUILT, ZERO LABELS REVIEWED. Current precision/recall is UNKNOWN.**

## Overview

This directory contains the independent evaluation harness for the Repository Knowledge Graph constructed by `pipeline/graph_builder.py`.

The pipeline extracts multi-layer code relationships:
- **Structural containment** (`contains`): File $\to$ Class $\to$ Function
- **Imports** (`imports`): File $\to$ Imported symbol / module
- **Class inheritance** (`inherits`): Class $\to$ Base class
- **Call resolution** (`calls`): Function $\to$ Target function

While call resolution operates under explicitly tracked confidence heuristics (`high_confidence`, `low_confidence`, `flagged`), real precision and recall metrics require verified human ground truth labels or external AST compiler oracles.

---

## Evaluation Workflow

### 1. Candidate Repositories
See [CANDIDATES.md](CANDIDATES.md) for the 5 benchmark repositories across Python, JavaScript/TypeScript, and Java.

### 2. Generate Stratified Annotation Sheet
Sample edges across core relationship types (`calls`, `imports`, `inherits`, `contains`):

```bash
python eval/graph/generate_sheet.py \
  --repo-path /path/to/repo \
  --repo-id org/repo \
  --sha <commit-sha> \
  --sample-size 50 \
  --output eval/graph/samples/sample.csv
```

All generated labels are initialized to **empty** (`""`).

### 3. Human Review & Annotation
Reviewers annotate the CSV according to [schema.json](schema.json):
- `TP` — True Positive (relationship accurately reflects code reality)
- `FP` — False Positive (relationship does not exist or target resolved incorrectly)
- `AMBIGUOUS` — Cannot be reliably determined from static code structure

### 4. Compute Metrics with Wilson 95% Confidence Intervals
Run the metrics script:

```bash
python eval/graph/metrics.py eval/graph/samples/sample.csv
```

- When unreviewed, it outputs: `NOT VALIDATED: 0 of N labels reviewed`.
- When reviewed, it computes overall and per-edge-type precision, recall, and F1 along with Wilson score 95% binomial confidence intervals.

---

## Independent Python AST Import Oracle

For Python repositories, an automated cross-check oracle compares tree-sitter graph builder imports against Python's built-in standard library `ast.parse`:

```bash
python eval/graph/import_oracle.py --repo-path /path/to/python_repo
```

Reports:
- Total Oracle AST import count vs Graph Builder import count
- True positive matches
- False positives in builder
- False negatives in builder
- Jaccard & Dice agreement rates
