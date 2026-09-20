# LLM Evaluation Lab

A small, reproducible review tool that turns **human-scored response evaluations** into an auditable JSON report and a readable Markdown summary.

The useful part is not an invented leaderboard: it is a reliable path from a review rubric to response-level decisions, critical-failure flags and comparisons on the **same test cases**.

> **Portfolio demonstration.** The included CedarDesk dataset is entirely synthetic. Prompts, responses and illustrative scores were authored with AI assistance; they have not been independently human-reviewed. The tool makes no model calls, and the output is not evidence about any real model or client. `draft` and `revised` are fictional response variants.

## What it does

- Validates required fields, exact score dimensions, unique IDs and consistent prompts across variants.
- Rejects missing scores, booleans used as numbers, out-of-range scores, non-finite numbers and invalid weights.
- Computes weighted scores on a 1–5 scale; a human-marked critical failure overrides an otherwise passing score.
- Reports per-dimension means, passes, failures and critical failures without silently dropping poor responses.
- Compares variants using shared case IDs only and explicitly counts unmatched cases.
- Produces deterministic JSON and Markdown reports with a hash of the canonical input.
- Runs entirely locally using the Python standard library: no account, API key, model download or paid service.

## Quick start

Use Python **3.10 or newer**. No packages need to be installed.

```shell
python evaluation_lab.py examples/synthetic_evaluations.json --output-dir reports/demo
python -m unittest discover -s tests -v
```

On Windows, `py -3` can replace `python` if needed.

The first command creates `reports/demo/report.json` and `reports/demo/report.md`. Existing files with those names in the selected output directory are replaced. Invalid inputs fail before any reports are written. A file-system failure can leave a partial report pair; the CLI reports that failure rather than claiming success.

**Read the output:** [sample Markdown report](reports/demo/report.md) · [sample JSON report](reports/demo/report.json) · [input dataset](examples/synthetic_evaluations.json).

## How scoring works

```text
weighted_score = sum(dimension_score × dimension_weight)
pass = weighted_score >= threshold AND critical_failure == false
```

Every dimension is required. Scores can be decimal numbers from 1 to 5. All dimension weights must be greater than zero and sum to 1, within a floating-point tolerance of 0.000000001. Accepted floating-point drift is normalized before scoring. Pass/fail is decided before display rounding.

The sample rubric weights grounding at 40%, instruction following at 30%, clarity at 20% and privacy/safe handling at 10%, with a 3.5 pass threshold. These are **example choices**, not universal evaluation standards. The [review guide](docs/review-guide.md) defines anchors and critical-failure examples.

A critical-failure flag does **not** turn a score into zero or remove it from averages. It prevents a pass and remains separately visible. This avoids hiding a serious failure inside a good-looking mean.

### Synthetic example: why the gate matters

One fictional response identifies the correct refund-request window but promises an unauthorized guaranteed refund. Its illustrative weighted score is 3.5, meeting the numerical threshold; its critical-failure flag still makes the decision **FAIL**. The tool applies the reviewer's flag—it does not discover the policy violation itself.

## Bring your own authorized reviews

1. Define the use case, reference material, scoring anchors and critical-failure rules before reviewing responses.
2. Create a JSON file using the [input schema guide](docs/input-schema.md). Use sanitized material; never commit private client data.
3. Assign human scores and notes for every dimension. Use the same `case_id` and identical prompt when comparing variants.
4. Set `synthetic` accurately and explain the response/score origin in `provenance`.
5. Run the CLI and inspect individual failures, case coverage and dimension scores—not just the average.

For private local experiments, `private-data/` and the default `reports/latest/` output are ignored by Git. A `.gitignore` is not a security boundary; inspect files and Git history before publishing anything.

```shell
python evaluation_lab.py private-data/my_reviews.json
```

Exit codes: `0` success, `2` invalid input or CLI arguments, `1` file-system error.

## Architecture

```text
JSON input
  → strict schema + score validation
  → weighted response decisions + critical gates
  → aggregate summaries + case-matched comparisons
  → deterministic JSON and Markdown reports
```

`evaluation_lab.py` keeps the core operations separate: `validate`, `evaluate`, `render_markdown` and `main`. Tests exercise the pure functions and the real file-based command path. There are no network operations or external dependencies.

## Limits, intentionally

- This is **review aggregation**, not automatic grading, model inference or a full evaluation platform.
- The tool cannot establish whether human judgments or reference material are correct.
- One review per case/variant is supported. There is no multi-reviewer adjudication or inter-rater reliability measurement.
- Comparisons are descriptive: no significance tests, confidence intervals, model rankings or claims about production performance.
- There is no access control, encryption, secret scanning or automatic personal-data redaction.
- Markdown and JSON include reviewer notes. Private inputs can produce private outputs.
- The input hash aids reproducibility; it is not a signature or independent proof of authenticity.

## Project context

An independent portfolio project by **Dhairya Sharma**, focused on making AI review work structured, inspectable and reproducible. Code was developed with AI assistance and verified using the included automated tests. The project contains no employer code, confidential evaluation material or real contributor records.

Potential next steps—**not implemented**—include multiple reviewers, agreement analysis and an HTML report. The current scope stays small enough to inspect and run without infrastructure.
