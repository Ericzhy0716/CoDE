"""CPU-only adapter checks using original AST functions and synthetic tensors.

These prove engineering guards, not GPU compatibility or method performance.
"""
import ast
import builtins
from contextlib import nullcontext
import itertools
import json
import math
from pathlib import Path
import symtable
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import upstream_diagnostic as adapter

UPSTREAM = ROOT / "upstream" / "CoDE-Stop"


class Scalar(float):
    """Enough tensor-scalar arithmetic to preserve the upstream zero division."""
    def item(self):
        return float(self)

    def __add__(self, value):
        return Scalar(float(self) + float(value))

    __radd__ = __add__

    def __sub__(self, value):
        return Scalar(float(self) - float(value))

    def __rsub__(self, value):
        return Scalar(float(value) - float(self))

    def __truediv__(self, value):
        if not value:
            return Scalar(math.copysign(math.inf, self) if self else math.nan)
        return Scalar(float(self) / float(value))


class Token(int):
    def item(self):
        return int(self)


class Tensor:
    device = "fake:0"

    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return self.values

    def unsqueeze(self, dim):
        return self

    def to(self, device):
        return self


class Tokenizer:
    eos_token_id = 99

    def __call__(self, text, **kwargs):
        return {"input_ids": [9] if text == "</think>" else [8]}

    def decode(self, values, **kwargs):
        return " ".join(str(int(value)) for value in values)


class Model:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        return {"logits": [[next(self.steps)]], "past_key_values": None}


def probe_function(stage):
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(empty_cache=lambda: None), no_grad=nullcontext,
        tensor=Tensor, max=lambda step, dim: (Scalar(step[1]), Token(step[0])),
        log=lambda value: Scalar(math.log(value)),
        exp=lambda value: Scalar(math.exp(value)))
    namespace = {"torch": fake_torch,
                 "F": SimpleNamespace(softmax=lambda values, dim: values)}
    adapter._extract(UPSTREAM / f"method_{stage}.py", ("calcu_max_probs_w_kv",), namespace)
    return namespace["calcu_max_probs_w_kv"]


def guarded_backend(stage):
    backend = adapter.Backend.__new__(adapter.Backend)
    backend.stage, backend.probe_index = stage, 0
    backend.positions, backend.events, backend.warnings = [123], [], []
    backend.tokenizer = Tokenizer()
    seen = []
    backend.callback = seen.append
    return backend, seen


class OriginalProbeTests(unittest.TestCase):
    def check_probe(self, stage, steps):
        backend, seen = guarded_backend(stage)
        model = Model(steps)
        call = lambda: backend._guard_probe(probe_function(stage))(
            model, Tensor([1, 2]), None, backend.tokenizer)
        return backend, seen, model, call

    def test_normal_three_tokens_keep_legacy_denominator(self):
        for stage in ("deer", "codestop"):
            with self.subTest(stage=stage):
                backend, seen, model, call = self.check_probe(
                    stage, [(5, .9), (6, .64), (9, .7)])
                result = call()
                self.assertAlmostEqual(result["total_prob_max"], .8)
                self.assertTrue(result["ended_with_think"])
                self.assertEqual(model.calls, 3)
                self.assertEqual(seen[0]["stop_token_index"], 123)
                self.assertEqual(len(backend.events), 1)

    def test_one_and_two_tokens_are_logged_then_rejected(self):
        for stage in ("deer", "codestop"):
            for steps in ([(9, .8)], [(5, .9), (9, .7)]):
                with self.subTest(stage=stage, count=len(steps)):
                    backend, seen, model, call = self.check_probe(stage, steps)
                    with self.assertRaisesRegex(ValueError, "<=2"):
                        call()
                    self.assertEqual(len(seen), 1)
                    self.assertEqual(model.calls, len(steps))
                    json.dumps(backend.events, allow_nan=False)
                    confidence = seen[0]["probe"]["total_prob_max"]
                    self.assertEqual(confidence, {"nonfinite": "inf"} if len(steps) == 1 else 1.)

    def test_cap_remains_twenty_one_and_warns(self):
        for stage in ("deer", "codestop"):
            with self.subTest(stage=stage):
                backend, seen, model, call = self.check_probe(stage, [(5, .8)] * 21)
                result = call()
                self.assertEqual(model.calls, 21)
                self.assertEqual(len(result["token_ids"]), 21)
                self.assertAlmostEqual(result["total_prob_max"], .8 ** (19 / 20))
                self.assertFalse(result["ended_with_think"])
                self.assertEqual(len(backend.warnings), 1)
                self.assertEqual(len(seen), 1)

    def test_eos_does_not_change_original_loop_but_guard_rejects(self):
        for stage in ("deer", "codestop"):
            with self.subTest(stage=stage):
                backend, seen, model, call = self.check_probe(stage, [(99, .8)] + [(5, .8)] * 20)
                with self.assertRaisesRegex(ValueError, "EOS"):
                    call()
                self.assertEqual(model.calls, 21)
                self.assertEqual(seen[0]["probe"]["token_ids"][0], 99)
                self.assertEqual(len(backend.events), 1)

    def test_nonfinite_confidence_is_logged_then_rejected(self):
        for stage in ("deer", "codestop"):
            with self.subTest(stage=stage):
                backend, seen, model, call = self.check_probe(
                    stage, [(5, .9), (6, math.nan), (9, .7)])
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    call()
                self.assertEqual(len(seen), 1)
                self.assertEqual(model.calls, 3)
                json.dumps(backend.events, allow_nan=False)


class ExtractionTests(unittest.TestCase):
    def test_actual_shared_namespace_resolves_all_runtime_globals(self):
        source = ast.parse(Path(adapter.__file__).read_text(encoding="utf-8"))
        # Derive shared names from production source, so a missing F is caught.
        shared = next(node.value for node in ast.walk(source)
                      if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                      and any(isinstance(target, ast.Name) and target.id == "shared"
                              for target in node.targets))
        available = {key.value for key in shared.keys}
        cache_names = ("clone_cache", "cache_to_device", "get_cache_devices")
        groups = [
            (("cache_utils.py", cache_names),),
            (("models.py", ("generate",)), ("method_prompts.py", ("method_step_by_step",))),
            (("inference.py", ("generic_forceans",)),),
            (("method_deer.py", ("calcu_max_probs_w_kv", "method_deer")),),
            (("method_codestop.py", ("compute_ramping_deer_threshold", "compute_degeneration_score",
                                      "calcu_max_probs_w_kv", "method_codestop")),),
        ]

        def referenced_globals(table):
            names = {symbol.get_name() for symbol in table.get_symbols()
                     if symbol.is_global() and symbol.is_referenced()}
            for child in table.get_children():
                names.update(referenced_globals(child))
            return names

        for group in groups:
            namespace = {name: None for name in available | set(cache_names)}
            selected = []
            for filename, names in group:
                adapter._extract(UPSTREAM / filename, names, namespace)
                tree = ast.parse((UPSTREAM / filename).read_text(encoding="utf-8"))
                selected.extend(node for node in tree.body
                                if isinstance(node, ast.FunctionDef) and node.name in names)
            for node in selected:
                table = symtable.symtable(ast.unparse(node), "<upstream-test>", "exec")
                # Function body tables exclude annotation-only module references.
                used = set().union(*(referenced_globals(child) for child in table.get_children()))
                unresolved = used - set(namespace) - set(dir(builtins))
                self.assertEqual(unresolved, set(), node.name)

    def test_annotations_do_not_require_upstream_import_side_effects(self):
        namespace = {}
        adapter._extract(UPSTREAM / "models.py", ("generate",), namespace)
        self.assertNotIn("AutoModelForCausalLM", namespace)
        self.assertIsInstance(namespace["generate"].__annotations__["model"], str)

    def test_log_setting_preserves_original_degeneration_formula(self):
        namespace = {"np": math, "itertools": itertools}
        adapter._extract(UPSTREAM / "method_codestop.py", ("compute_degeneration_score",), namespace)
        score = namespace["compute_degeneration_score"]
        self.assertAlmostEqual(score([100, 200, 400], [.9, .8, .7], use_log=True), 2 + math.log(2))
        self.assertEqual(score([100, 200, 400], [.9, .8, .7], use_log=False), 0)


class StageEvidenceTests(unittest.TestCase):
    def test_empty_forced_answer_fails_and_retains_returned_output(self):
        backend = adapter.Backend.__new__(adapter.Backend)
        output = {"response": "reasoning and forced prefix", "forced": True, "final_part": ""}
        backend.functions = {"vanilla": lambda **kwargs: output}
        backend.config = {"seed": 42, "max_new_tokens": 100}
        noop = lambda *args: None
        backend.np = SimpleNamespace(random=SimpleNamespace(seed=noop))
        backend.torch = SimpleNamespace(manual_seed=noop, cuda=SimpleNamespace(
            manual_seed_all=noop, synchronize=noop, reset_peak_memory_stats=noop))
        backend.device = "fake:0"
        backend.model, backend.tokenizer, backend.sample, backend.metadata = None, None, {}, {}
        backend._forceans_preflight = noop
        backend._metrics = lambda *args: {"fixture_only": True}
        with self.assertRaisesRegex(adapter.DiagnosticStageError, "empty final_part") as caught:
            backend.run("vanilla", {"response": "base response"})
        self.assertEqual(caught.exception.partial["method_output"], output)

    def test_rollback_reports_stop_and_actual_answer_position(self):
        backend = adapter.Backend.__new__(adapter.Backend)
        backend.stage, backend.positions, backend.probe_index = "codestop", [100, 200, 400], 3
        backend.config = {"rollback": True, "ewt": True, "degen_threshold": 2}
        output = {"stopped_early": True, "prob_checks": [
            {"total_prob_max": .9, "stop_token_idx": 100},
            {"total_prob_max": .8, "stop_token_idx": 200},
            {"total_prob_max": .7, "stop_token_idx": 400, "degen_score": 3,
             "effective_deer_threshold": .95, "ended_with_think": True}]}
        decision = backend._decision(output)
        self.assertEqual(decision["reasons"], ["degeneration"])
        self.assertEqual(decision["stopping_checkpoint_token_position"], 400)
        self.assertEqual(decision["final_answer_prefix_token_position"], 100)


if __name__ == "__main__":
    unittest.main()
