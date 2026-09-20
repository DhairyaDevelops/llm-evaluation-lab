# Input schema: version 1

All fields below are required. Unknown fields, duplicate JSON keys and non-standard JSON numbers such as `NaN` are rejected. JSON must be UTF-8.

## Dataset

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | integer | Exactly `1`; `true` is not accepted |
| `dataset_label` | string | Non-empty, without outer whitespace |
| `synthetic` | boolean | `true` for invented demonstration material; label truthfully |
| `provenance` | string | Explain where responses and scores came from; do not include private identities |
| `rubric` | object | `pass_threshold` and `dimensions` |
| `evaluations` | array | At least one evaluation |

The provenance statement is copied into the report. The software cannot independently verify it.

## Rubric

`pass_threshold` is a finite number from 1 to 5. `dimensions` is a non-empty list of objects with:

- `id`: a unique lowercase identifier matching `[a-z][a-z0-9_]*`.
- `label`: a non-empty human-readable name.
- `weight`: a finite numeric value greater than zero and at most 1. All weights must sum to 1 within an absolute tolerance of `1e-9`.

## Evaluation

| Field | Type | Rule |
| --- | --- | --- |
| `id` | string | Unique within the dataset |
| `case_id` | string | Identifies the same prompt across variants |
| `variant` | string | Human-readable response configuration label, not necessarily a model name |
| `prompt` | string | Non-empty; identical for all records with this `case_id` |
| `response` | string | Non-empty response being reviewed |
| `scores` | object | Exactly one numeric 1–5 score per rubric dimension; no missing or extra keys |
| `critical_failure` | boolean | Reviewer's explicit gate decision; never inferred by the tool |
| `review_note` | string | Non-empty explanation/evidence for the human judgment |

Only one record per `(case_id, variant)` pair is accepted. Duplicate pairs would otherwise give some cases extra influence. If you need repeated runs, define distinct case/run identifiers and understand that each record then has equal weight; the tool does not model statistical independence.

All text fields reject outer whitespace and most control characters. Embedded tabs/newlines are allowed. Empty responses are not supported; model timeouts and no-response failures require a future schema rather than silently being treated as a successful review.

## Output behavior

Each response receives an unrounded internal weighted score. It passes only if the score meets the threshold and `critical_failure` is false. Reports display rounded values, so a very close threshold miss may visually round to the threshold; the explicit decision and reason remain authoritative.

Each variant summary includes all its records. Pairwise comparisons include only shared case IDs, and show left/right unmatched counts. A comparison with zero shared cases contains an explanation instead of a misleading score delta.

The canonical input hash uses JSON with sorted object keys, compact separators and ASCII escapes. Array ordering remains significant. Reordering input records therefore changes the input hash even though the aggregate numbers are unchanged.

The report includes scores, decisions, provenance and reviewer notes, but does not repeat the full prompts/responses. Treat it with the same care as its inputs. Saving a report is not a privacy review.
