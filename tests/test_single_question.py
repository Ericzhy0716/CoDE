"""CPU-only contract tests. These are not model or method-performance evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import diagnostic_core as core


class BackendFixture:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def run(self, stage, dependency):
        self.calls.append(stage)
        if stage in self.fail:
            raise RuntimeError("diagnostic interruption")
        if stage != "base":
            assert dependency["response"]
        return {"method_output": {"response": "reasoning</think>\\boxed{402}", "response_tokens": 10},
                "metrics": {"fixture_only": True}, "generation_calls": [], "warnings": []}


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)
        self.cfg = core.load_config(ROOT / "configs/single_question.json")
        self.sources = {"fixture": "not_a_model_run"}
        self.fp = core.ensure_manifest(self.run_dir, self.cfg, self.sources)
        self.backend = BackendFixture()

    def run_stage(self, stage):
        return core.execute_stage(self.run_dir, stage, self.cfg, self.fp, self.backend)

    def test_resume_after_method_failure_keeps_generation_and_other_method(self):
        self.run_stage("base")
        self.run_stage("vanilla")
        self.backend.fail.add("deer")
        with self.assertRaises(RuntimeError):
            self.run_stage("deer")
        self.run_stage("codestop")
        self.assertTrue((self.run_dir / "deer.error.json").exists())
        self.assertFalse((self.run_dir / "deer.json").exists())
        self.assertEqual(self.run_stage("base"), "reused")
        self.assertEqual(self.run_stage("vanilla"), "reused")
        self.backend.fail.clear()
        self.run_stage("deer")
        self.assertEqual(self.backend.calls, ["base", "vanilla", "deer", "codestop", "deer"])
        grades = core.grade_run(self.run_dir)
        self.assertEqual(set(grades["stages"]), set(core.STAGES))

    def test_grading_failure_does_not_erase_or_regenerate_output(self):
        self.run_stage("base")
        original = (self.run_dir / "base.json").read_bytes()
        with patch.object(core, "grade_response", side_effect=RuntimeError("judge unavailable")):
            with self.assertRaises(RuntimeError):
                core.grade_run(self.run_dir)
        self.assertEqual((self.run_dir / "base.json").read_bytes(), original)
        self.assertEqual(self.run_stage("base"), "reused")
        self.assertEqual(self.backend.calls, ["base"])
        self.assertTrue(core.grade_run(self.run_dir)["stages"]["base"]["correct"])

    def test_changed_config_or_dependency_cannot_reuse_old_method(self):
        self.run_stage("base")
        self.run_stage("vanilla")
        changed = {**self.cfg, "seed": self.cfg["seed"] + 1}
        with self.assertRaisesRegex(ValueError, "Config or source changed"):
            core.ensure_manifest(self.run_dir, changed, self.sources)
        base = core.read_json(self.run_dir / "base.json")
        base["method_output"]["response"] = "changed"
        core.atomic_json(self.run_dir / "base.json", base)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            self.run_stage("vanilla")

    def test_nonfinite_save_cannot_destroy_previous_record(self):
        path = self.run_dir / "existing.json"
        core.atomic_json(path, {"value": 1})
        with self.assertRaises(ValueError):
            core.atomic_json(path, {"value": float("nan")})
        self.assertEqual(core.read_json(path), {"value": 1})
        core.append_event(self.run_dir / "events.jsonl", {"confidence": float("nan")})
        event = core.read_json(self.run_dir / "events.jsonl")
        self.assertEqual(event["confidence"], {"invalid_numeric_value": "nan"})

    def test_standalone_method_checks_grandparent_and_inspect_rejects_stale_grade(self):
        self.run_stage("base")
        self.run_stage("vanilla")
        core.grade_run(self.run_dir)
        base = core.read_json(self.run_dir / "base.json")
        base["method_output"]["response"] = "replaced valid base</think>\\boxed{401}"
        base.pop("record_sha256")
        base["record_sha256"] = core.digest(base)
        core.atomic_json(self.run_dir / "base.json", base)
        with self.assertRaisesRegex(ValueError, "dependency changed"):
            self.run_stage("deer")
        self.assertEqual(self.backend.calls, ["base", "vanilla"])
        report = core.inspect_run(self.run_dir)
        self.assertEqual(report["stages"]["vanilla"]["status"], "invalid")
        self.assertEqual(report["grading"]["status"], "stale_or_invalid")

    def test_missing_shard_is_detected_even_when_config_exists(self):
        snapshot = self.run_dir / "snapshot"
        snapshot.mkdir()
        for name in ("config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json"):
            core.atomic_json(snapshot / name, {})
        core.atomic_json(snapshot / "model.safetensors.index.json", {"weight_map": {"weight": "missing.safetensors"}})
        with self.assertRaisesRegex(ValueError, "Incomplete model shard"):
            core.validate_snapshot(snapshot)

    def test_incomplete_or_unparseable_answer_is_not_scored_as_wrong(self):
        for response in ("still thinking \\boxed{402}", "x</think>\\boxed{402", "x</think>\\boxed{2*201}"):
            result = core.grade_response(response, "402")
            self.assertEqual(result["status"], "needs_review")
            self.assertIsNone(result["correct"])
        self.assertFalse(core.grade_response("x</think>\\boxed{401}", "402")["correct"])
        self.assertTrue(core.grade_response("x</think>\\boxed{804/2}", "402")["correct"])


if __name__ == "__main__":
    unittest.main()
