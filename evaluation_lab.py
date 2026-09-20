"""Validate and aggregate human-scored response reviews. No model calls."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


class ValidationError(ValueError):
    """Input does not satisfy the documented evaluation schema."""


def _object(value: Any, where: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{where}: expected an object")
    missing = fields - value.keys()
    extra = value.keys() - fields
    if missing:
        raise ValidationError(f"{where}: missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValidationError(f"{where}: unknown fields: {', '.join(sorted(extra))}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where}: expected non-empty text")
    if value != value.strip() or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValidationError(f"{where}: remove outer whitespace/control characters")
    return value


def _number(value: Any, where: str, minimum: float, maximum: float) -> float:
    # bool is a subclass of int; True must never silently become a score of 1.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where}: expected a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"{where}: expected a finite number") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValidationError(f"{where}: must be finite and between {minimum} and {maximum}")
    return number


def validate(data: Any) -> dict[str, Any]:
    """Return the unchanged input only after validating every required field."""
    _object(data, "dataset", {"schema_version", "dataset_label", "synthetic", "provenance", "rubric", "evaluations"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("schema_version: must be integer 1")
    _text(data["dataset_label"], "dataset_label")
    _text(data["provenance"], "provenance")
    if type(data["synthetic"]) is not bool:
        raise ValidationError("synthetic: expected true or false")

    rubric = _object(data["rubric"], "rubric", {"pass_threshold", "dimensions"})
    _number(rubric["pass_threshold"], "rubric.pass_threshold", 1, 5)
    dimensions = rubric["dimensions"]
    if not isinstance(dimensions, list) or not dimensions:
        raise ValidationError("rubric.dimensions: expected a non-empty list")
    names: set[str] = set()
    weights = []
    for index, dimension in enumerate(dimensions):
        where = f"rubric.dimensions[{index}]"
        _object(dimension, where, {"id", "label", "weight"})
        name = _text(dimension["id"], f"{where}.id")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in names:
            raise ValidationError(f"{where}.id: use a unique lowercase identifier")
        names.add(name)
        _text(dimension["label"], f"{where}.label")
        weight = _number(dimension["weight"], f"{where}.weight", 0, 1)
        if weight == 0:
            raise ValidationError(f"{where}.weight: must be greater than zero")
        weights.append(weight)
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValidationError("rubric.dimensions: weights must sum to 1")

    evaluations = data["evaluations"]
    if not isinstance(evaluations, list) or not evaluations:
        raise ValidationError("evaluations: expected a non-empty list")
    ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    prompts: dict[str, str] = {}
    for index, entry in enumerate(evaluations):
        where = f"evaluations[{index}]"
        _object(entry, where, {"id", "case_id", "variant", "prompt", "response", "scores", "critical_failure", "review_note"})
        for field in ("id", "case_id", "variant", "prompt", "response", "review_note"):
            _text(entry[field], f"{where}.{field}")
        if entry["id"] in ids:
            raise ValidationError(f"{where}.id: duplicate evaluation ID")
        ids.add(entry["id"])
        pair = (entry["case_id"], entry["variant"])
        if pair in pairs:
            raise ValidationError(f"{where}: duplicate case/variant pair")
        pairs.add(pair)
        if entry["case_id"] in prompts and prompts[entry["case_id"]] != entry["prompt"]:
            raise ValidationError(f"{where}.prompt: the same case_id must use the same prompt")
        prompts[entry["case_id"]] = entry["prompt"]
        if type(entry["critical_failure"]) is not bool:
            raise ValidationError(f"{where}.critical_failure: expected true or false")
        scores = _object(entry["scores"], f"{where}.scores", names)
        for name, score in scores.items():
            _number(score, f"{where}.scores.{name}", 1, 5)
    return data


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _rounded(number: float) -> float:
    return round(number, 6)


def evaluate(data: Any) -> dict[str, Any]:
    """Produce deterministic summaries; judgments are supplied by the reviewer."""
    validate(data)
    dimensions = data["rubric"]["dimensions"]
    # Renormalize tiny accepted floating-point differences, not invalid weights.
    total_weight = math.fsum(float(d["weight"]) for d in dimensions)
    weights = {d["id"]: float(d["weight"]) / total_weight for d in dimensions}
    threshold = float(data["rubric"]["pass_threshold"])
    raw_scores: dict[str, float] = {}
    records = []
    for entry in sorted(data["evaluations"], key=lambda e: (e["variant"], e["case_id"])):
        score = math.fsum(float(entry["scores"][name]) * weight for name, weight in weights.items())
        raw_scores[entry["id"]] = score
        reasons = []
        if score < threshold:
            reasons.append("below_pass_threshold")
        if entry["critical_failure"]:
            reasons.append("critical_failure")
        records.append({
            "id": entry["id"], "case_id": entry["case_id"], "variant": entry["variant"],
            "scores": entry["scores"], "weighted_score": _rounded(score),
            "critical_failure": entry["critical_failure"], "passed": not reasons,
            "decision_reasons": reasons, "review_note": entry["review_note"],
        })

    def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "review_count": len(entries),
            "pass_count": sum(e["passed"] for e in entries),
            "fail_count": sum(not e["passed"] for e in entries),
            "critical_failure_count": sum(e["critical_failure"] for e in entries),
            "pass_rate": _rounded(sum(e["passed"] for e in entries) / len(entries)),
            "mean_weighted_score": _rounded(_mean([raw_scores[e["id"]] for e in entries])),
            "mean_dimension_scores": {
                name: _rounded(_mean([float(e["scores"][name]) for e in entries])) for name in weights
            },
        }

    variants = sorted({e["variant"] for e in records})
    groups = {variant: [e for e in records if e["variant"] == variant] for variant in variants}
    comparisons = []
    for left, right in itertools.combinations(variants, 2):
        left_cases = {e["case_id"]: e for e in groups[left]}
        right_cases = {e["case_id"]: e for e in groups[right]}
        shared = sorted(left_cases.keys() & right_cases.keys())
        comparison: dict[str, Any] = {
            "left_variant": left, "right_variant": right, "matched_case_ids": shared,
            "matched_case_count": len(shared),
            "left_unmatched_case_count": len(left_cases.keys() - right_cases.keys()),
            "right_unmatched_case_count": len(right_cases.keys() - left_cases.keys()),
        }
        if shared:
            left_matched = [left_cases[case] for case in shared]
            right_matched = [right_cases[case] for case in shared]
            comparison["left_matched"] = summarize(left_matched)
            comparison["right_matched"] = summarize(right_matched)
            comparison["mean_score_delta_right_minus_left"] = _rounded(_mean([
                raw_scores[right_cases[case]["id"]] - raw_scores[left_cases[case]["id"]] for case in shared
            ]))
            comparison["pass_count_delta_right_minus_left"] = (
                sum(e["passed"] for e in right_matched) - sum(e["passed"] for e in left_matched)
            )
        else:
            comparison["note"] = "No shared case IDs; a paired comparison is not available."
        comparisons.append(comparison)

    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return {
        "report_schema_version": 1,
        "dataset_label": data["dataset_label"], "synthetic": data["synthetic"],
        "provenance": data["provenance"],
        "input_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "method": {
            "score_range": [1, 5], "pass_threshold": threshold, "dimensions": dimensions,
            "pass_rule": "Weighted score >= threshold AND critical_failure is false.",
            "aggregation": "Equal weight per reviewed response. Failed/gated responses remain in all means.",
            "comparison": "Shared case IDs only; descriptive results, not statistical significance or a model benchmark.",
        },
        "overall": summarize(records),
        "variants": {variant: summarize(groups[variant]) for variant in variants},
        "comparisons": comparisons, "evaluations": records,
    }


def _md(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def render_markdown(report: dict[str, Any]) -> str:
    status = (
        "SYNTHETIC DEMONSTRATION — authored responses and illustrative scores; not independently human-reviewed and not a model benchmark."
        if report["synthetic"] else
        "HUMAN-SCORED INPUT — source, permissions and reviewer judgments are not independently verified by this tool."
    )
    lines = [
        f"# {_md(report['dataset_label'])}", "", f"> {status}", "",
        _md(report["provenance"]), "", "## Method", "",
        "This tool aggregates supplied reviewer scores (illustrative in synthetic examples); it does not generate responses, grade correctness or call a model.", "",
        f"Scores: 1–5. Pass threshold: {report['method']['pass_threshold']:g}. Any reviewer-marked critical failure overrides a passing score.", "",
        "| Dimension | Weight |", "| --- | ---: |",
    ]
    for dimension in report["method"]["dimensions"]:
        lines.append(f"| {_md(dimension['label'])} | {dimension['weight']:.0%} |")
    lines.extend([
        "", "## Variant summaries", "",
        "All reviewed responses, including critical failures, contribute to means. Overall summaries can mix different case sets; use paired comparisons below when comparing variants.", "",
        "| Variant | Reviewed | Passed | Failed | Critical | Mean / 5 | Pass rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for variant, summary in report["variants"].items():
        lines.append(f"| {_md(variant)} | {summary['review_count']} | {summary['pass_count']} | {summary['fail_count']} | {summary['critical_failure_count']} | {summary['mean_weighted_score']:.2f} | {summary['pass_rate']:.1%} |")
    overall = report["overall"]
    lines.extend([
        "", f"Total: {overall['review_count']} reviews; {overall['pass_count']} pass; {overall['fail_count']} fail; {overall['critical_failure_count']} critical failures.",
        "", "## Matched-case comparisons", "",
        "Positive score deltas favor the right-hand variant on these cases only. They do not establish general superiority or statistical significance.", "",
    ])
    if not report["comparisons"]:
        lines.extend(["Only one variant is present; no comparison is available.", ""])
    for comparison in report["comparisons"]:
        lines.extend([
            f"### {_md(comparison['left_variant'])} → {_md(comparison['right_variant'])}", "",
            f"Shared cases: {comparison['matched_case_count']}. Unmatched: left {comparison['left_unmatched_case_count']}, right {comparison['right_unmatched_case_count']}.", "",
        ])
        if comparison["matched_case_count"]:
            lines.extend([
                f"Matched mean score: {comparison['left_matched']['mean_weighted_score']:.2f} → {comparison['right_matched']['mean_weighted_score']:.2f} / 5.", "",
                f"Mean score delta: {comparison['mean_score_delta_right_minus_left']:+.2f}; pass-count delta: {comparison['pass_count_delta_right_minus_left']:+d}.", "",
            ])
        else:
            lines.extend([comparison["note"], ""])
    lines.extend([
        "## Review decisions", "",
        "| Case | Variant | Score / 5 | Decision | Reasons | Reviewer note |",
        "| --- | --- | ---: | --- | --- | --- |",
    ])
    for entry in report["evaluations"]:
        reasons = ", ".join(entry["decision_reasons"]) or "meets supplied rubric"
        decision = "PASS" if entry["passed"] else "FAIL"
        lines.append(f"| {_md(entry['case_id'])} | {_md(entry['variant'])} | {entry['weighted_score']:.2f} | {decision} | {_md(reasons)} | {_md(entry['review_note'])} |")
    lines.extend([
        "", "## Limitations and traceability", "",
        "- Scores, reference material and critical-failure flags are supplied inputs, not independently verified facts.",
        "- Small or selected case sets cannot establish production quality, safety or model rankings.",
        "- One evaluation per case/variant is supported; inter-rater agreement is not measured.",
        "- Display rounding never determines pass/fail. JSON retains six decimal places.",
        "- Reports include reviewer notes. Use only public, synthetic or appropriately approved material.",
        "", f"Canonical input SHA-256: `{report['input_sha256']}`", "",
    ])
    return "\n".join(lines)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def load_dataset(path: Path) -> Any:
    def invalid_constant(value: str) -> None:
        raise ValidationError(f"JSON contains non-standard number: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys, parse_constant=invalid_constant)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON dataset of human-scored reviews")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/latest"), help="Writes report.json and report.md; existing reports are replaced")
    args = parser.parse_args(argv)
    try:
        targets = [args.output_dir / "report.json", args.output_dir / "report.md"]
        if args.input.resolve() in [target.resolve() for target in targets]:
            raise ValidationError("Input file cannot also be an output report")
        report = evaluate(load_dataset(args.input))
        markdown = render_markdown(report)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        targets[0].write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        targets[1].write_text(markdown, encoding="utf-8")
    except (ValidationError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"File error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {targets[0]} and {targets[1]}")
    print("Synthetic demonstration; no model calls were made." if report["synthetic"] else "Aggregated supplied human scores; no model calls were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
