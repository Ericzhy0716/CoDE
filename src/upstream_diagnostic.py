"""Single-question diagnostic adapter for pinned upstream CoDE-Stop functions.

This module executes selected function definitions, never upstream module imports.
It retains the legacy algorithms, including confidence arithmetic and the 21-token
probe cap. Undefined/degenerate probe outputs fail the stage instead of silently
changing the stopping rule. No GPU libraries are imported until Backend creation.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import itertools
import math
from pathlib import Path
import random
import time
from typing import Any, Callable


class DiagnosticStageError(RuntimeError):
    """A failed stage whose completed diagnostic evidence remains inspectable."""

    def __init__(self, message: str, partial: dict[str, Any]):
        super().__init__(message)
        self.partial = partial


def _safe_evidence(value: Any) -> Any:
    """Represent invalid numbers explicitly without changing algorithm inputs."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, dict):
        return {key: _safe_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_evidence(item) for item in value]
    return value


def _extract(path: Path, names: tuple[str, ...], namespace: dict[str, Any]) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    missing = set(names) - definitions.keys()
    if missing:
        raise ValueError(f"Missing upstream functions in {path.name}: {sorted(missing)}")
    selected = ast.Module(body=[definitions[name] for name in names], type_ignores=[])
    exec(compile(selected, str(path), "exec"), namespace)


class Backend:
    """Execute base -> vanilla -> deer/codestop against one local Qwen3 snapshot."""

    def __init__(self, config: dict[str, Any], model_dir: Path,
                 event_callback: Callable[[dict[str, Any]], None]):
        import nltk
        import numpy as np
        import torch
        import torch.nn.functional as F
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from transformers.cache_utils import DynamicCache

        if transformers.__version__ != "4.51.3":
            raise RuntimeError("This diagnostic requires transformers==4.51.3")
        if torch.__version__.split("+")[0] != "2.9.1":
            raise RuntimeError("This diagnostic requires torch==2.9.1")
        if not torch.cuda.is_available():
            raise RuntimeError("A CUDA GPU is required; CPU execution is disabled")
        torch.cuda.set_device(0)
        if not torch.cuda.is_bf16_supported():
            raise RuntimeError("cuda:0 does not support the required BF16 execution")
        self.config, self.torch, self.np, self.nltk = config, torch, np, nltk
        self.device = torch.device("cuda:0")
        self.callback = event_callback
        self.stage, self.calls, self.events, self.warnings = "model_load", [], [], []
        self.sample = dict(config["sample"])
        if not str(self.sample.get("question", "")).strip():
            raise ValueError("config.sample.question must be nonempty")
        if config.get("nltk_dir"):
            nltk.data.path.insert(0, str(config["nltk_dir"]))
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False)
        for marker in (config["stop_word"], "</think>"):
            if len(self.tokenizer.encode(marker, add_special_tokens=False)) != 1:
                raise RuntimeError(f"Upstream diagnostic requires single-token {marker!r}")
        if self.tokenizer.eos_token_id is None:
            raise RuntimeError("The tokenizer must define an EOS token")
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        torch.cuda.synchronize(self.device)
        torch.cuda.reset_peak_memory_stats(self.device)
        load_start = time.perf_counter()
        self.model = AutoModelForCausalLM.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False,
            torch_dtype=torch.bfloat16).to(self.device).eval()
        if self.model.config.model_type != "qwen3":
            raise RuntimeError("This backend supports Qwen3 causal language models only")
        for key, value in {"temperature": 0.6, "top_p": 0.95,
                           "top_k": 20, "min_p": 0}.items():
            setattr(self.model.generation_config, key, value)
        torch.cuda.synchronize(self.device)
        self.metadata = {
            "generation_config": self.model.generation_config.to_dict(),
            "tokenizer_chat_template": self.tokenizer.chat_template,
            "tokenizer_ids": {"eos": self.tokenizer.eos_token_id,
                              "pad": self.tokenizer.pad_token_id,
                              "stop_word": self.tokenizer.encode(config["stop_word"], add_special_tokens=False),
                              "end_think": self.tokenizer.encode("</think>", add_special_tokens=False)},
            "attention_implementation": getattr(self.model.config, "_attn_implementation", None),
            "transformers_version": transformers.__version__, "torch_version": torch.__version__,
            "cuda_version": torch.version.cuda, "gpu_name": torch.cuda.get_device_name(0)}
        self._emit({"kind": "model_loaded", "stage": "model_load",
                    "elapsed_seconds": time.perf_counter() - load_start,
                    "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(self.device),
                    "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(self.device),
                    "metadata": self.metadata})

        root = Path(__file__).resolve().parents[1] / "upstream" / "CoDE-Stop"
        shared = {"torch": torch, "F": F, "transformers": transformers, "np": np,
                  "nltk": nltk, "deepcopy": deepcopy, "itertools": itertools,
                  "DynamicCache": DynamicCache, "Any": Any, "Callable": Callable}
        cache_ns = dict(shared)
        _extract(root / "cache_utils.py",
                 ("clone_cache", "cache_to_device", "get_cache_devices"), cache_ns)
        shared.update({name: cache_ns[name] for name in
                       ("clone_cache", "cache_to_device", "get_cache_devices")})
        base_ns = dict(shared)
        _extract(root / "models.py", ("generate",), base_ns)
        _extract(root / "method_prompts.py", ("method_step_by_step",), base_ns)
        vanilla_ns = dict(shared)
        _extract(root / "inference.py", ("generic_forceans",), vanilla_ns)
        self.functions = {"base": base_ns["method_step_by_step"],
                          "vanilla": vanilla_ns["generic_forceans"]}
        for stage in ("deer", "codestop"):
            namespace = dict(shared)
            names = ("calcu_max_probs_w_kv", f"method_{stage}")
            if stage == "codestop":
                names = ("compute_ramping_deer_threshold",
                         "compute_degeneration_score") + names
            _extract(root / f"method_{stage}.py", names, namespace)
            namespace["calcu_max_probs_w_kv"] = self._guard_probe(
                namespace["calcu_max_probs_w_kv"])
            self.functions[stage] = namespace[f"method_{stage}"]
        self.model.generate = self._audit_generate(self.model.generate)

    def _emit(self, event: dict[str, Any]) -> None:
        evidence = _safe_evidence(event)
        self.events.append(deepcopy(evidence))
        self.callback(evidence)

    def _guard_probe(self, original: Callable[..., dict[str, Any]]) -> Callable:
        def checked(*args: Any, **kwargs: Any) -> dict[str, Any]:
            index = self.probe_index
            self.probe_index += 1
            result = original(*args, **kwargs)
            self._emit({"kind": "checkpoint", "stage": self.stage,
                        "checkpoint_index": index,
                        "stop_token_index": self.positions[index],
                        "probe": deepcopy(result)})
            ids = result["token_ids"]
            confidence = float(result["total_prob_max"])
            if len(ids) <= 2:
                raise ValueError("Legacy confidence is undefined/degenerate for <=2 probe tokens")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Probe confidence is non-finite or outside [0,1]")
            if self.tokenizer.eos_token_id in ids:
                raise ValueError("Probe generated EOS; upstream EOS handling is not valid for this trace")
            if any(not math.isfinite(float(p)) for p in result["token_probs"]):
                raise ValueError("Probe token probabilities contain non-finite values")
            if not result["ended_with_think"]:
                self.warnings.append(f"checkpoint {index}: probe reached legacy cap without </think>")
            return result
        return checked

    def _audit_generate(self, original: Callable) -> Callable:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            inputs = args[0] if args else kwargs.get("input_ids", kwargs.get("inputs"))
            call = {"stage": self.stage, "call_index": len(self.calls),
                    "input_token_ids": inputs.detach().cpu().tolist(),
                    "max_new_tokens": kwargs.get("max_new_tokens"),
                    "do_sample": kwargs.get("do_sample"),
                    "has_prefix_cache": kwargs.get("past_key_values") is not None}
            self.calls.append(call)
            try:
                output = original(*args, **kwargs)
                sequences = getattr(output, "sequences", output)
                call.update({"status": "ok",
                             "output_token_ids": sequences.detach().cpu().tolist(),
                             "generated_token_ids": sequences[:, inputs.shape[1]:].detach().cpu().tolist()})
                self._emit({"kind": "generation", **deepcopy(call)})
                return output
            except Exception as exc:
                call.update({"status": "failed", "error": str(exc),
                             "error_type": type(exc).__name__})
                raise
        return recorded

    def _forceans_preflight(self, dependency: dict[str, Any]) -> None:
        response = dependency.get("response", "")
        if not isinstance(response, str) or not response.strip():
            raise ValueError("Vanilla forcing requires a nonempty base response")
        if not dependency.get("messages"):
            raise ValueError("Vanilla forcing requires the base messages")
        budget = int(self.config["max_new_tokens"])
        if budget <= 50:
            raise ValueError("The mathematical force-answer path requires a budget above 50")
        if len(self.tokenizer.encode(response)) < budget - 50:
            return
        sentences = self.nltk.sent_tokenize(response)
        if len(sentences) == 1:
            sentences = response.split("\n\n")
        while sentences:
            if budget - len(self.tokenizer.encode(" ".join(sentences))) >= 50:
                return
            sentences = sentences[:-1]
        raise ValueError("Upstream force-answer truncation cannot retain a sentence with 50 tokens left")

    def _metrics(self, start: float, seed: int) -> dict[str, Any]:
        self.torch.cuda.synchronize(self.device)
        return {"elapsed_seconds": time.perf_counter() - start,
                "peak_cuda_allocated_bytes": self.torch.cuda.max_memory_allocated(self.device),
                "peak_cuda_reserved_bytes": self.torch.cuda.max_memory_reserved(self.device),
                "seed": seed, "device": "cuda:0", "dtype": "bfloat16",
                "timing_scope": ("cached_trajectory_offline_replay" if self.stage in
                                 ("deer", "codestop") else self.stage),
                "includes_diagnostic_logging": True,
                "is_online_early_stop_latency": False,
                "model_id": self.config["model_id"],
                "model_revision": self.config["model_revision"]}

    def _decision(self, output: dict[str, Any]) -> dict[str, Any]:
        reasons, stop_position, answer_position = [], None, None
        if self.stage in ("deer", "codestop"):
            if output["stopped_early"]:
                last = output["prob_checks"][-1]
                stop_position = self.positions[self.probe_index - 1]
                answer_position = stop_position
                if self.stage == "codestop" and self.config["rollback"]:
                    answer_position = max(output["prob_checks"], key=lambda p: p["total_prob_max"])["stop_token_idx"]
                threshold = (self.config["deer_threshold"] if self.stage == "deer"
                             else last["effective_deer_threshold"])
                if ((not self.config["ewt"] or last["ended_with_think"])
                        and last["total_prob_max"] > threshold):
                    reasons.append("confidence")
                if self.stage == "codestop" and last["degen_score"] > self.config["degen_threshold"]:
                    reasons.append("degeneration")
            else:
                reasons.append("no_checkpoints" if not self.positions else "no_stopping_condition")
        else:
            reasons.append("base_generation" if self.stage == "base" else
                           ("forced_answer" if output["forced"] else "base_retained"))
        return {"reasons": reasons, "candidate_checkpoint_token_positions": self.positions,
                "checked_checkpoint_token_positions": self.positions[:self.probe_index],
                "stopping_checkpoint_token_position": stop_position,
                "final_answer_prefix_token_position": answer_position}

    def run(self, stage: str, dependency_output_or_none: dict[str, Any] | None) -> dict[str, Any]:
        if stage not in self.functions:
            raise ValueError(f"Unknown diagnostic stage: {stage}")
        self.stage, self.calls, self.events, self.warnings = stage, [], [], []
        self.probe_index, self.positions = 0, []
        seed = int(self.config["seed"]) + {"base": 0, "vanilla": 1,
                                          "deer": 2, "codestop": 2}[stage]
        random.seed(seed)
        self.np.random.seed(seed)
        self.torch.manual_seed(seed)
        self.torch.cuda.manual_seed_all(seed)
        self.torch.cuda.synchronize(self.device)
        self.torch.cuda.reset_peak_memory_stats(self.device)
        start = time.perf_counter()
        output = None
        try:
            dependency = dependency_output_or_none
            if stage != "base" and not isinstance(dependency, dict):
                raise ValueError(f"{stage} requires its successful dependency method_output")
            if stage != "base" and (dependency.get("error") or dependency.get("status") in ("failed", "error")):
                raise ValueError("A failed dependency cannot be used as a successful method output")
            if stage != "base" and not str(dependency.get("response", "")).strip():
                raise ValueError("Dependency response is empty")
            if stage == "vanilla":
                self._forceans_preflight(dependency)
            if stage in ("deer", "codestop"):
                stop_ids = self.tokenizer(self.config["stop_word"], add_special_tokens=False)["input_ids"]
                stop_ids += [self.tokenizer.eos_token_id]
                trace_ids = self.tokenizer(dependency["response"])["input_ids"]
                self.positions = [i for i, token in enumerate(trace_ids) if token in stop_ids]
                if not self.positions:
                    self.warnings.append("No checkpoints: stopping/probe branches were not exercised")
            params = {"model": self.model, "tokenizer": self.tokenizer,
                      "sample": self.sample, "B": int(self.config["max_new_tokens"])}
            if stage != "base":
                params["sample_response"] = {"method_output": dependency}
            if stage in ("deer", "codestop"):
                params.update({key: self.config[key] for key in ("stop_word", "ewt", "cp_cache")})
            if stage == "deer":
                params["threshold"] = self.config["deer_threshold"]
            elif stage == "codestop":
                params.update({key: self.config[key] for key in (
                    "conf_threshold", "degen_threshold", "ramp_steps", "ramp_min", "use_log", "rollback")})
            output = self.functions[stage](**params)
            if not isinstance(output.get("response"), str) or not output["response"].strip():
                raise ValueError("Upstream returned an empty response")
            if stage == "vanilla" and output.get("forced") and not output.get("final_part", "").strip():
                raise ValueError("Forced-answer generation returned an empty final_part")
            if stage in ("deer", "codestop"):
                if len(output.get("prob_checks", [])) != self.probe_index:
                    raise ValueError("Returned checkpoint records do not match observed probes")
            return {"method_output": output, "metrics": self._metrics(start, seed),
                    "generation_calls": self.calls, "warnings": self.warnings,
                    "metadata": self.metadata, "decision": self._decision(output)}
        except Exception as exc:
            partial = {"stage": stage, "generation_calls": self.calls,
                       "warnings": self.warnings, "events": self.events,
                       "metadata": self.metadata,
                       "method_output": _safe_evidence(output),
                       "error_type": type(exc).__name__, "error": str(exc)}
            try:
                partial["metrics"] = self._metrics(start, seed)
            except Exception as metric_exc:
                partial["metrics_error"] = str(metric_exc)
            raise DiagnosticStageError(f"{stage} failed: {exc}", partial) from exc
