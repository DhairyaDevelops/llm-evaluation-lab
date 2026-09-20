"""Run with: python -m unittest discover -s tests -v"""

import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import evaluation_lab as lab


ROOT = Path(__file__).resolve().parents[1]


def dataset():
    return {
        "schema_version": 1,
        "dataset_label": "Synthetic test fixture",
        "synthetic": True,
        "provenance": "Authored fixture; no model calls or real customer data.",
        "rubric": {
            "pass_threshold": 3.5,
            "dimensions": [
                {"id": "accuracy", "label": "Accuracy", "weight": 0.6},
                {"id": "clarity", "label": "Clarity", "weight": 0.4},
            ],
        },
        "evaluations": [{
            "id": "review-1", "case_id": "case-1", "variant": "a",
            "prompt": "Use the supplied fictional reference.",
            "response": "A fictional response.",
            "scores": {"accuracy": 5, "clarity": 2},
            "critical_failure": False, "review_note": "Synthetic fixture note.",
        }],
    }


def extra_review(data, review_id, case_id, variant, score=4):
    entry = copy.deepcopy(data["evaluations"][0])
    entry.update(id=review_id, case_id=case_id, variant=variant)
    entry["scores"] = {name: score for name in entry["scores"]}
    data["evaluations"].append(entry)
    return entry


class ValidationTests(unittest.TestCase):
    def test_valid_input_is_not_mutated(self):
        data = dataset()
        original = copy.deepcopy(data)
        self.assertIs(lab.validate(data), data)
        lab.evaluate(data)
        self.assertEqual(data, original)

    def test_rejects_missing_top_level_fields(self):
        for field in dataset():
            with self.subTest(field=field):
                data = dataset()
                del data[field]
                with self.assertRaises(lab.ValidationError):
                    lab.evaluate(data)

    def test_rejects_unknown_fields(self):
        for location in ("root", "rubric", "dimension", "evaluation"):
            with self.subTest(location=location):
                data = dataset()
                target = {"root": data, "rubric": data["rubric"],
                          "dimension": data["rubric"]["dimensions"][0],
                          "evaluation": data["evaluations"][0]}[location]
                target["unexpected"] = "not accepted"
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_invalid_schema_version(self):
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                data = dataset()
                data["schema_version"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_invalid_scores(self):
        for value in (True, False, None, "4", 0, 5.1, -1, float("nan"), float("inf"), -float("inf"), 10 ** 400):
            with self.subTest(value=str(value)[:40]):
                data = dataset()
                data["evaluations"][0]["scores"]["accuracy"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_accepts_score_boundaries_and_decimals(self):
        for value in (1, 5, 2.5):
            with self.subTest(value=value):
                data = dataset()
                data["evaluations"][0]["scores"]["accuracy"] = value
                lab.validate(data)

    def test_rejects_missing_score(self):
        data = dataset()
        del data["evaluations"][0]["scores"]["accuracy"]
        with self.assertRaisesRegex(lab.ValidationError, "missing fields"):
            lab.validate(data)

    def test_rejects_extra_score(self):
        data = dataset()
        data["evaluations"][0]["scores"]["helpfulness"] = 3
        with self.assertRaisesRegex(lab.ValidationError, "unknown fields"):
            lab.validate(data)

    def test_rejects_invalid_weights(self):
        for value in (True, "0.6", 0, -0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                data = dataset()
                data["rubric"]["dimensions"][0]["weight"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_weight_total_not_one(self):
        data = dataset()
        data["rubric"]["dimensions"][0]["weight"] = 0.5
        with self.assertRaisesRegex(lab.ValidationError, "sum to 1"):
            lab.validate(data)

    def test_accepts_and_normalizes_tiny_weight_drift(self):
        data = dataset()
        data["rubric"]["dimensions"][0]["weight"] = 0.60000000001
        data["evaluations"][0]["scores"] = {"accuracy": 5, "clarity": 5}
        report = lab.evaluate(data)
        self.assertEqual(report["overall"]["mean_weighted_score"], 5)

    def test_rejects_invalid_threshold(self):
        for value in (True, "3", 0, 5.01, float("nan")):
            with self.subTest(value=value):
                data = dataset()
                data["rubric"]["pass_threshold"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_empty_or_nonlist_evaluations(self):
        for value in ([], {}, None, ""):
            with self.subTest(value=value):
                data = dataset()
                data["evaluations"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_empty_dimensions(self):
        data = dataset()
        data["rubric"]["dimensions"] = []
        with self.assertRaises(lab.ValidationError):
            lab.validate(data)

    def test_rejects_duplicate_or_invalid_dimension_ids(self):
        for value in ("accuracy", "Bad ID", "9start"):
            with self.subTest(value=value):
                data = dataset()
                data["rubric"]["dimensions"][1]["id"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_duplicate_review_id(self):
        data = dataset()
        extra_review(data, "review-1", "case-2", "a")
        with self.assertRaisesRegex(lab.ValidationError, "duplicate evaluation ID"):
            lab.validate(data)

    def test_rejects_duplicate_case_variant_pair(self):
        data = dataset()
        extra_review(data, "review-2", "case-1", "a")
        with self.assertRaisesRegex(lab.ValidationError, "duplicate case/variant"):
            lab.validate(data)

    def test_rejects_mismatched_prompts_for_same_case(self):
        data = dataset()
        extra_review(data, "review-2", "case-1", "b")["prompt"] = "Different task."
        with self.assertRaisesRegex(lab.ValidationError, "same prompt"):
            lab.validate(data)

    def test_rejects_nonboolean_flags(self):
        for field in ("synthetic", "critical_failure"):
            for value in (0, 1, "false", None):
                with self.subTest(field=field, value=value):
                    data = dataset()
                    target = data if field == "synthetic" else data["evaluations"][0]
                    target[field] = value
                    with self.assertRaises(lab.ValidationError):
                        lab.validate(data)

    def test_rejects_empty_or_invalid_text(self):
        for value in ("", "   ", " padded ", 42, None, "bad\x00text"):
            with self.subTest(value=value):
                data = dataset()
                data["evaluations"][0]["review_note"] = value
                with self.assertRaises(lab.ValidationError):
                    lab.validate(data)

    def test_rejects_nonobject_input(self):
        for value in ([], None, "text", 3):
            with self.subTest(value=value), self.assertRaises(lab.ValidationError):
                lab.validate(value)


class ScoringTests(unittest.TestCase):
    def test_weighted_score_and_dimension_means(self):
        report = lab.evaluate(dataset())
        self.assertEqual(report["overall"]["mean_weighted_score"], 3.8)
        self.assertEqual(report["overall"]["mean_dimension_scores"], {"accuracy": 5, "clarity": 2})
        self.assertEqual(report["overall"]["pass_count"], 1)

    def test_critical_gate_overrides_high_score_without_zeroing_it(self):
        data = dataset()
        data["evaluations"][0]["critical_failure"] = True
        report = lab.evaluate(data)
        result = report["evaluations"][0]
        self.assertFalse(result["passed"])
        self.assertEqual(result["weighted_score"], 3.8)
        self.assertEqual(result["decision_reasons"], ["critical_failure"])
        self.assertEqual(report["overall"]["critical_failure_count"], 1)
        self.assertEqual(report["overall"]["mean_weighted_score"], 3.8)

    def test_both_failure_reasons_are_retained(self):
        data = dataset()
        data["evaluations"][0]["scores"] = {"accuracy": 1, "clarity": 1}
        data["evaluations"][0]["critical_failure"] = True
        reasons = lab.evaluate(data)["evaluations"][0]["decision_reasons"]
        self.assertEqual(reasons, ["below_pass_threshold", "critical_failure"])

    def test_exact_threshold_passes(self):
        data = dataset()
        data["evaluations"][0]["scores"] = {"accuracy": 3.5, "clarity": 3.5}
        self.assertTrue(lab.evaluate(data)["evaluations"][0]["passed"])

    def test_display_rounding_does_not_decide_pass(self):
        data = dataset()
        data["rubric"]["pass_threshold"] = 3.50000001
        data["evaluations"][0]["scores"] = {"accuracy": 3.5, "clarity": 3.5}
        result = lab.evaluate(data)["evaluations"][0]
        self.assertEqual(result["weighted_score"], 3.5)
        self.assertFalse(result["passed"])

    def test_single_variant_has_no_comparison(self):
        self.assertEqual(lab.evaluate(dataset())["comparisons"], [])

    def test_comparison_uses_shared_cases_not_unmatched_scores(self):
        data = dataset()
        extra_review(data, "review-2", "case-1", "b", 4)
        extra_review(data, "review-3", "unmatched", "b", 1)
        report = lab.evaluate(data)
        comparison = report["comparisons"][0]
        self.assertEqual(comparison["matched_case_ids"], ["case-1"])
        self.assertEqual(comparison["right_unmatched_case_count"], 1)
        self.assertEqual(comparison["left_unmatched_case_count"], 0)
        self.assertEqual(comparison["mean_score_delta_right_minus_left"], 0.2)
        self.assertEqual(comparison["right_matched"]["mean_weighted_score"], 4)
        self.assertEqual(report["variants"]["b"]["mean_weighted_score"], 2.5)

    def test_no_shared_cases_does_not_invent_delta(self):
        data = dataset()
        extra_review(data, "review-2", "case-2", "b", 4)
        comparison = lab.evaluate(data)["comparisons"][0]
        self.assertEqual(comparison["matched_case_count"], 0)
        self.assertNotIn("mean_score_delta_right_minus_left", comparison)
        self.assertIn("No shared case IDs", comparison["note"])

    def test_comparison_pass_delta_respects_critical_gate(self):
        data = dataset()
        data["evaluations"][0]["critical_failure"] = True
        extra_review(data, "review-2", "case-1", "b", 4)["critical_failure"] = False
        comparison = lab.evaluate(data)["comparisons"][0]
        self.assertEqual(comparison["pass_count_delta_right_minus_left"], 1)

    def test_pairwise_comparisons_for_three_variants(self):
        data = dataset()
        extra_review(data, "review-2", "case-1", "b", 4)
        extra_review(data, "review-3", "case-1", "c", 3)
        self.assertEqual(len(lab.evaluate(data)["comparisons"]), 3)

    def test_fixture_totals_and_known_means(self):
        report = lab.evaluate(lab.load_dataset(ROOT / "examples/synthetic_evaluations.json"))
        self.assertEqual(report["overall"]["review_count"], 10)
        self.assertEqual(report["overall"]["pass_count"], 6)
        self.assertEqual(report["overall"]["fail_count"], 4)
        self.assertEqual(report["overall"]["critical_failure_count"], 3)
        self.assertEqual(report["variants"]["draft"]["mean_weighted_score"], 2.84)
        self.assertEqual(report["variants"]["revised"]["mean_weighted_score"], 4.78)
        self.assertEqual(report["overall"]["mean_weighted_score"], 3.81)
        self.assertEqual(report["comparisons"][0]["mean_score_delta_right_minus_left"], 1.94)

    def test_outputs_are_deterministic(self):
        first = lab.evaluate(dataset())
        second = lab.evaluate(dataset())
        self.assertEqual(first, second)
        self.assertEqual(lab.render_markdown(first), lab.render_markdown(second))

    def test_hash_tracks_input_changes(self):
        data = dataset()
        first_hash = lab.evaluate(data)["input_sha256"]
        data["evaluations"][0]["review_note"] = "A changed review note."
        self.assertNotEqual(first_hash, lab.evaluate(data)["input_sha256"])


class FileAndReportTests(unittest.TestCase):
    def test_synthetic_markdown_has_warning_and_decisions(self):
        markdown = lab.render_markdown(lab.evaluate(dataset()))
        self.assertIn("SYNTHETIC DEMONSTRATION", markdown)
        self.assertIn("not a model benchmark", markdown)
        self.assertIn("| case-1 | a | 3.80 | PASS |", markdown)
        self.assertIn("Only one variant", markdown)

    def test_nonsynthetic_report_does_not_claim_independent_verification(self):
        data = dataset()
        data["synthetic"] = False
        markdown = lab.render_markdown(lab.evaluate(data))
        self.assertIn("not independently verified", markdown)
        self.assertNotIn("SYNTHETIC DEMONSTRATION", markdown)

    def test_markdown_escapes_table_delimiters_html_and_links(self):
        data = dataset()
        data["evaluations"][0]["review_note"] = "a | b\n<script>bad</script> [link](example)"
        markdown = lab.render_markdown(lab.evaluate(data))
        self.assertIn("a \\| b &lt;script&gt;", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertIn("\\[link\\]", markdown)

    def test_json_rejects_duplicate_keys_and_nonstandard_numbers(self):
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(lab.ValidationError):
                    lab.load_dataset(path)

    def test_cli_writes_both_reports_and_reproduces_checked_in_example(self):
        source = ROOT / "examples/synthetic_evaluations.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results"
            with contextlib.redirect_stdout(io.StringIO()):
                code = lab.main([str(source), "--output-dir", str(output)])
            self.assertEqual(code, 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report, lab.evaluate(lab.load_dataset(source)))
            self.assertEqual((output / "report.md").read_text(encoding="utf-8"), lab.render_markdown(report))
            checked_in = ROOT / "reports/demo/report.json"
            if checked_in.exists():
                self.assertEqual(report, json.loads(checked_in.read_text(encoding="utf-8")))

    def test_invalid_cli_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{}", encoding="utf-8")
            output = Path(directory) / "results"
            with contextlib.redirect_stderr(io.StringIO()):
                code = lab.main([str(path), "--output-dir", str(output)])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_malformed_json_returns_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lab.main([str(path)]), 2)

    def test_missing_file_returns_filesystem_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lab.main([str(Path(directory) / "missing.json")]), 1)

    def test_input_cannot_be_overwritten_by_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.json"
            content = json.dumps(dataset())
            source.write_text(content, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lab.main([str(source), "--output-dir", directory]), 2)
            self.assertEqual(source.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
