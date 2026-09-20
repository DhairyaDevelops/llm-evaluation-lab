# Case study: making response reviews reproducible

**LLM Evaluation Lab · Independent portfolio project · Python standard library**

## The problem

A review average can look reassuring while hiding a serious failure. Comparing response variants is also misleading if each was reviewed against a different set of prompts. This project explores how to make those decisions inspectable without building a full evaluation platform.

The result is a local command-line tool that validates supplied review scores, applies a weighted rubric and produces linked response-level decisions, variant summaries and matched-case comparisons. It aggregates judgments; it does not replace a reviewer.

## Design choices

- **Validate before summarizing.** Missing dimensions, duplicate case/variant pairs, inconsistent prompts, invalid weights and booleans masquerading as scores are rejected.
- **Keep serious failures visible.** A supplied critical-failure flag overrides a numerically passing score. The score stays in the average rather than being silently removed or replaced with zero.
- **Compare equivalent cases.** Pairwise comparisons use shared case IDs only and report unmatched counts. They make no statistical-significance claim.
- **Make results reproducible.** The same input produces deterministic JSON and Markdown reports. A canonical input hash helps identify the reviewed dataset.
- **Keep setup small.** Python's standard library is sufficient; no model service, network call, API key or paid dependency is needed.

## Walk through the demonstration

Run the [synthetic CedarDesk dataset](examples/synthetic_evaluations.json):

```shell
python evaluation_lab.py examples/synthetic_evaluations.json --output-dir reports/demo
```

Open the [report](reports/demo/report.md) and find `refund_policy` under the fictional `draft` variant. The response correctly identifies a 14-day refund-request window but invents guaranteed approval. Its illustrative weighted score is **3.5**, equal to the pass threshold. The supplied critical flag still makes the decision **FAIL**.

Next, inspect the five matched cases across `draft` and `revised`. The sample totals are 10 reviews, six passes, four failures and three critical failures. These figures demonstrate the calculation—not improvement in an actual model. Every response and score is authored demonstration material, not collected model output or an independently human-reviewed result.

## Verification

**43 automated tests passed**, including a run against a fresh clone of the published repository. Coverage includes validation failures, threshold boundaries, critical gates, known totals, matched/unmatched comparisons, deterministic reports and the file-based CLI.

```shell
python -m unittest discover -s tests -v
```

## Boundaries and contribution

This independent project demonstrates rubric implementation, defensive validation, review traceability and report design. Code and synthetic examples were developed with AI assistance; no unaided-authorship or client-delivery claim is made.

The tool cannot verify a reviewer's judgment, detect sensitive information or establish production model quality. It supports one review per case/variant, not reviewer agreement or adjudication. Reports contain supplied notes and need the same privacy care as their inputs.
