"""Durable, staged orchestration. No ML imports or network calls at import time."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream" / "CoDE-Stop"
STAGES = ("base", "vanilla", "deer", "codestop")
DEPENDENCY = {"base": None, "vanilla": "base", "deer": "vanilla", "codestop": "vanilla"}
PINNED_PACKAGES = {"torch": "2.9.1", "transformers": "4.51.3", "accelerate": "1.12.0", "nltk": "3.9.2"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    """Serialize before replacement: an invalid result cannot truncate an old file."""
    path = Path(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
            temp_path = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def diagnostic_value(value):
    """Retain nonfinite diagnostics as explicit strings, never as fake numeric scores."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalid_numeric_value": repr(value)}
    if isinstance(value, dict):
        return {str(k): diagnostic_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [diagnostic_value(v) for v in value]
    return value


def append_event(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(diagnostic_value(value), ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_config(path):
    cfg = read_json(path)
    if cfg.get("scope") != "single_question_diagnostic_only":
        raise ValueError("This entry point is limited to a single-question diagnostic, not benchmark evaluation.")
    if cfg.get("model_id") != "Qwen/Qwen3-4B" or not re.fullmatch(r"[0-9a-f]{40}", cfg.get("model_revision", "")):
        raise ValueError("Use Qwen/Qwen3-4B and an immutable 40-character model revision.")
    sample = cfg.get("sample", {})
    if not all(isinstance(sample.get(k), str) and sample[k].strip() for k in ("id", "question", "answer", "purpose")):
        raise ValueError("sample requires nonempty id, question, answer and purpose strings.")
    for key, low, high in (("max_new_tokens", 128, 8192), ("seed", 0, 2**31 - 4), ("ramp_steps", 0, 100)):
        value = cfg.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} must be an integer in [{low}, {high}].")
    for key in ("deer_threshold", "conf_threshold", "ramp_min", "degen_threshold"):
        value = cfg.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{key} must be finite.")
        if value < 0 or (key != "degen_threshold" and value > 1):
            raise ValueError(f"Invalid {key}.")
    if cfg["ramp_min"] > cfg["conf_threshold"]:
        raise ValueError("ramp_min must not exceed conf_threshold.")
    for key in ("ewt", "cp_cache", "use_log", "rollback"):
        if type(cfg.get(key)) is not bool:
            raise ValueError(f"{key} must be boolean.")
    if cfg["cp_cache"] or cfg["rollback"]:
        raise ValueError("First diagnostic requires cp_cache=false and rollback=false; cache validation is a later task.")
    if cfg.get("stop_word") != "Wait" or not cfg["ewt"] or not cfg["use_log"]:
        raise ValueError("Keep Wait, ewt=true and upstream use_log=true for this diagnostic.")
    return cfg


def verify_sources():
    pin = read_json(ROOT / "UPSTREAM.json")
    files = ("models.py", "method_prompts.py", "method_deer.py", "method_codestop.py", "cache_utils.py", "inference.py")
    hashes = {}
    for name in files:
        path = UPSTREAM / name
        if not path.is_file():
            raise ValueError("Pinned upstream missing. Run git submodule update --init --recursive.")
        hashes[name] = file_hash(path)
        if hashes[name] != pin["upstream_tracked_files_sha256"][name]:
            raise ValueError(f"Upstream source differs from pinned version: {name}")
    own_files = ("src/diagnostic_core.py", "src/upstream_diagnostic.py", "scripts/single_question.py")
    own = {name: file_hash(ROOT / name) for name in own_files}
    return {"upstream_commit": pin["upstream_commit"], "upstream_sha256": hashes, "runner_sha256": own}


def validate_snapshot(snapshot):
    """Check every indexed shard, not just config.json. Loading performs the tensor check."""
    snapshot = Path(snapshot)
    required = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json"]
    for name in required:
        if not (snapshot / name).is_file():
            raise ValueError(f"Incomplete model snapshot: missing {name}")
    index = read_json(snapshot / "model.safetensors.index.json")
    shards = sorted(set(index.get("weight_map", {}).values()))
    if not shards:
        raise ValueError("Empty model shard index.")
    for name in shards:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Invalid model shard path.")
        if not (snapshot / name).is_file() or (snapshot / name).stat().st_size < 100:
            raise ValueError(f"Incomplete model shard: {name}")
    return {"snapshot": str(snapshot), "shards": shards, "weight_bytes": sum((snapshot / s).stat().st_size for s in shards)}


def environment_check(cfg, cache_dir, nltk_dir):
    problems = []
    versions = {}
    for name, expected in PINNED_PACKAGES.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        versions[name] = actual
        if actual.split("+")[0] != expected:
            problems.append(f"{name}: require {expected}, found {actual}")
    report = {"checked_at": utc_now(), "python": sys.version, "packages": versions, "problems": problems}
    if problems:
        return report
    import torch
    import nltk
    from huggingface_hub import snapshot_download
    nltk.data.path.insert(0, str(nltk_dir))
    try:
        nltk.data.find("tokenizers/punkt_tab/english/")
    except LookupError:
        problems.append("Missing NLTK punkt_tab; run the prepare command before starting a run.")
    if not torch.cuda.is_available():
        problems.append("CUDA GPU unavailable; this diagnostic does not silently fall back to CPU/Mac.")
    else:
        props = torch.cuda.get_device_properties(0)
        report["gpu"] = {"name": props.name, "memory_bytes": props.total_memory, "capability": list(torch.cuda.get_device_capability(0)), "torch_cuda": torch.version.cuda}
        if not torch.cuda.is_bf16_supported():
            problems.append("GPU/software stack does not support BF16.")
    try:
        snapshot = snapshot_download(cfg["model_id"], revision=cfg["model_revision"], cache_dir=str(cache_dir), local_files_only=True)
        report["model"] = validate_snapshot(snapshot)
    except Exception as exc:
        problems.append(f"Model cache unavailable/incomplete ({type(exc).__name__}); run prepare first.")
    report["installed_distributions"] = dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions() if d.metadata["Name"]))
    return report


@contextmanager
def run_lock(run_dir):
    """One process per run; OS releases the lock after crashes/disconnects."""
    import fcntl
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".lock").open("a", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another process is using this run directory.") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ensure_manifest(run_dir, cfg, sources):
    identity = {"config": cfg, "sources": sources, "schema_version": 1}
    signature = digest(identity)
    path = run_dir / "manifest.json"
    if path.exists():
        previous = read_json(path)
        if previous.get("identity") != identity or previous.get("fingerprint") != signature:
            raise ValueError("Config or source changed. Use a new --run-dir; old outputs will not be overwritten.")
    else:
        if any((run_dir / f"{s}.json").exists() for s in STAGES):
            raise ValueError("Stage outputs exist without a manifest; use a new run directory.")
        atomic_json(path, {"created_at": utc_now(), "fingerprint": signature, "identity": identity})
    return signature


def execute_stage(run_dir, stage, cfg, fingerprint, backend):
    """Persist generation before grading; hash dependencies before reusing any stage."""
    dependency = DEPENDENCY[stage]
    dependency_record = read_saved_stage(run_dir, dependency, fingerprint) if dependency else None
    dependency_hash = digest(dependency_record) if dependency_record else None
    path = run_dir / f"{stage}.json"
    if path.exists():
        old = read_saved_stage(run_dir, stage, fingerprint)
        if old.get("dependency_sha256") != dependency_hash:
            raise ValueError(f"Cannot reuse inconsistent {stage} output; inspect it and use a new run directory.")
        return "reused"
    try:
        result = backend.run(stage, dependency_record["method_output"] if dependency_record else None)
        record = {"stage": stage, "status": "completed", "finished_at": utc_now(), "fingerprint": fingerprint,
                  "dependency_sha256": dependency_hash, "scope": cfg["scope"], **result}
        record["record_sha256"] = digest(record)
        atomic_json(path, record)
    except Exception as exc:
        error = {"stage": stage, "status": "failed", "at": utc_now(), "fingerprint": fingerprint,
                 "error_type": type(exc).__name__, "message": str(exc), "partial": getattr(exc, "partial", None)}
        append_event(run_dir / "events.jsonl", error)
        atomic_json(run_dir / f"{stage}.error.json", diagnostic_value(error))
        raise
    return "completed"


def verify_record(record, stage, fingerprint):
    contents = {k: v for k, v in record.items() if k != "record_sha256"}
    if (record.get("status") != "completed" or record.get("stage") != stage
            or record.get("fingerprint") != fingerprint or record.get("record_sha256") != digest(contents)):
        raise ValueError(f"Cannot reuse inconsistent {stage} record (identity or checksum mismatch).")


def read_saved_stage(run_dir, stage, fingerprint):
    """Validate the entire ancestor chain, including standalone method resumes."""
    record = read_json(run_dir / f"{stage}.json")
    verify_record(record, stage, fingerprint)
    dependency = DEPENDENCY[stage]
    expected = digest(read_saved_stage(run_dir, dependency, fingerprint)) if dependency else None
    if record.get("dependency_sha256") != expected:
        raise ValueError(f"Cannot reuse inconsistent {stage} record: dependency changed.")
    return record


def load_manifest(run_dir):
    manifest = read_json(run_dir / "manifest.json")
    if manifest.get("fingerprint") != digest(manifest["identity"]):
        raise ValueError("Manifest identity checksum mismatch.")
    return manifest


def grade_response(response, expected):
    """Strict integer/decimal/fraction teaching checker, deliberately not a benchmark judge."""
    # With Qwen thinking enabled, no closing tag means a final answer is unconfirmed.
    if "</think>" not in response:
        return {"status": "needs_review", "correct": None, "reason": "missing_thinking_end"}
    tail = response.rsplit("</think>", 1)[1]
    start = tail.rfind("\\boxed{")
    if start < 0:
        return {"status": "needs_review", "correct": None, "reason": "missing_boxed_answer"}
    content, depth = [], 1
    for char in tail[start + 7:]:
        depth += (char == "{") - (char == "}")
        if depth == 0:
            break
        content.append(char)
    if depth != 0:
        return {"status": "needs_review", "correct": None, "reason": "unfinished_box"}
    predicted = "".join(content).strip()
    # Do not evaluate arbitrary Python/SymPy expressions supplied by a model.
    number = r"[+-]?(?:\d+(?:\.\d+)?|\d+/[+-]?\d+)"
    if not re.fullmatch(number, predicted) or not re.fullmatch(number, expected.strip()):
        return {"status": "needs_review", "correct": None, "reason": "unsupported_expression", "answer": predicted}
    try:
        equal = Fraction(predicted) == Fraction(expected.strip())
    except (ValueError, ZeroDivisionError):
        return {"status": "needs_review", "correct": None, "reason": "invalid_numeric_answer", "answer": predicted}
    return {"status": "checked", "correct": equal, "answer": predicted}


def grade_run(run_dir):
    manifest = load_manifest(run_dir)
    grades = {"scope": "teaching_only_not_paper_evaluation", "fingerprint": manifest["fingerprint"], "stages": {}}
    for stage in STAGES:
        path = run_dir / f"{stage}.json"
        if path.exists():
            record = read_saved_stage(run_dir, stage, manifest["fingerprint"])
            grades["stages"][stage] = {"source_sha256": file_hash(path), **grade_response(record["method_output"]["response"], manifest["identity"]["config"]["sample"]["answer"])}
    atomic_json(run_dir / "grading.json", grades)
    return grades


def inspect_run(run_dir):
    report = {"run_dir": str(run_dir), "stages": {}}
    manifest = load_manifest(run_dir) if (run_dir / "manifest.json").exists() else None
    for stage in STAGES:
        if (run_dir / f"{stage}.json").exists():
            try:
                if manifest is None:
                    raise ValueError("Missing manifest.")
                record = read_saved_stage(run_dir, stage, manifest["fingerprint"])
                report["stages"][stage] = {"status": "completed", "warnings": record.get("warnings", []),
                                           "metrics": record.get("metrics", {}),
                                           "probe_count": len(record["method_output"].get("prob_checks", []))}
            except (ValueError, OSError) as exc:
                report["stages"][stage] = {"status": "invalid", "reason": str(exc)}
        else:
            report["stages"][stage] = {"status": "failed" if (run_dir / f"{stage}.error.json").exists() else "not_run"}
    grade_path = run_dir / "grading.json"
    if grade_path.exists():
        grades = read_json(grade_path)
        valid = manifest is not None and grades.get("fingerprint") == manifest["fingerprint"]
        completed = {s for s in STAGES if report["stages"][s]["status"] == "completed"}
        valid = valid and set(grades.get("stages", {})) == completed
        for stage, grade in grades.get("stages", {}).items():
            path = run_dir / f"{stage}.json"
            valid = valid and path.is_file() and grade.get("source_sha256") == file_hash(path)
        report["grading"] = grades if valid else {"status": "stale_or_invalid", "action": "inspect outputs, then run grade"}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "prepare", "check", "run", "grade", "inspect"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/single_question.json")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "runs/single-question")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data/model-cache")
    parser.add_argument("--nltk-dir", type=Path, default=ROOT / "data/nltk")
    parser.add_argument("--stage", choices=STAGES + ("all",), default="base")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            report = inspect_run(args.run_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if any(v["status"] == "invalid" for v in report["stages"].values()) else 0
        if args.command == "grade":
            with run_lock(args.run_dir):
                report = grade_run(args.run_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        cfg = load_config(args.config)
        sources = verify_sources()
        if args.command == "plan":
            print(json.dumps({"config": cfg, "upstream_commit": sources["upstream_commit"], "stages": list(STAGES),
                              "no_model_loaded_or_downloaded": True,
                              "notes": [f"Handwritten teaching sample, {cfg['max_new_tokens']}-token budget; not paper reproduction.",
                                        "cp_cache=false: repeated prefix prefill; no online speedup claim.",
                                        "Short/invalid probes fail the method and preserve diagnostics.",
                                        "No Wait checkpoint means the probing branch remains untested."]}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "prepare":
            from huggingface_hub import snapshot_download
            import nltk
            snapshot = snapshot_download(cfg["model_id"], revision=cfg["model_revision"], cache_dir=str(args.cache_dir), allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken"])
            args.nltk_dir.mkdir(parents=True, exist_ok=True)
            if not nltk.download("punkt_tab", download_dir=str(args.nltk_dir), quiet=False):
                raise ValueError("NLTK resource download failed.")
            print(json.dumps(validate_snapshot(snapshot), ensure_ascii=False, indent=2))
            return 0
        env = environment_check(cfg, args.cache_dir, args.nltk_dir)
        if args.command == "check" or env["problems"]:
            print(json.dumps(env, ensure_ascii=False, indent=2))
            return 1 if env["problems"] else 0
        with run_lock(args.run_dir):
            fingerprint = ensure_manifest(args.run_dir, cfg, sources)
            # Immutable environment per run: a migration needs a new directory.
            env_path = args.run_dir / "environment.json"
            if env_path.exists():
                prior = read_json(env_path)
                for key in ("packages", "gpu", "installed_distributions", "python"):
                    if prior.get(key) != env.get(key):
                        raise ValueError("Runtime environment changed; use a new --run-dir.")
            else:
                atomic_json(env_path, env)
            requested = list(STAGES) if args.stage == "all" else [args.stage]
            # Do not load the model until missing dependencies have been identified.
            for stage in requested:
                dep = DEPENDENCY[stage]
                if dep and dep not in requested and not (args.run_dir / f"{dep}.json").exists():
                    raise ValueError(f"Run --stage {dep} first.")
                if (args.run_dir / f"{stage}.json").exists():
                    read_saved_stage(args.run_dir, stage, fingerprint)
                elif dep and (args.run_dir / f"{dep}.json").exists():
                    read_saved_stage(args.run_dir, dep, fingerprint)
            from upstream_diagnostic import Backend
            backend = None
            failures = []
            for stage in requested:
                dep = DEPENDENCY[stage]
                if dep and not (args.run_dir / f"{dep}.json").exists():
                    failures.append(stage)
                    continue
                if not (args.run_dir / f"{stage}.json").exists() and backend is None:
                    append_event(args.run_dir / "events.jsonl", {"event": "model_load_started", "at": utc_now()})
                    backend = Backend({**cfg, "nltk_dir": str(args.nltk_dir.resolve())}, Path(env["model"]["snapshot"]), lambda event: append_event(args.run_dir / "events.jsonl", {"at": utc_now(), **event}))
                try:
                    status = execute_stage(args.run_dir, stage, cfg, fingerprint, backend)
                    print(f"{stage}: {status}", flush=True)
                except Exception as exc:
                    failures.append(stage)
                    print(f"{stage}: failed ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
            print(json.dumps(grade_run(args.run_dir), ensure_ascii=False, indent=2))
            return 1 if failures else 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
