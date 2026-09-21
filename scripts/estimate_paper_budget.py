#!/usr/bin/env python3
"""Offline API budget scenarios using CoDE-Stop Tables 1 and 3 (B=32768).

This only performs arithmetic. It never calls an API, downloads weights, or
claims that a provider supports the paper's models or probing protocol.
Prices are explicit CNY per million tokens; one common rate applies per run.
"""

import argparse
import json
import math


SOURCE = "https://arxiv.org/html/2604.04930v2"
TRAJECTORIES = {"math500": 1000, "aime": 900, "gsm8k": 1319, "gpqad": 990}
# Each value is (Table 1 Vanilla mean output tokens, Table 3 mean steps).
PAPER = {
    "qwen3-4b": {"math500": (5210, 5.4), "aime": (16326, 14.4),
                   "gsm8k": (2306, 2.5), "gpqad": (9536, 12.6)},
    "qwen3-14b": {"math500": (4878, 5.3), "aime": (15137, 15.7),
                    "gsm8k": (1668, 2.0), "gpqad": (8447, 12.5)},
    "deepseek-r1-distill-llama-8b": {
        "math500": (4576, 22.3), "aime": (14461, 98.8),
        "gsm8k": (1840, 8.3), "gpqad": (9177, 70.4)},
    "nemotron-nano-8b-v1": {"math500": (3258, 4.7), "aime": (11130, 15.8),
                            "gsm8k": (1211, 2.2), "gpqad": (7318, 11.9)},
}
WARNINGS = [
    "Planning scenario, not a measured bill, guaranteed upper bound, or full-paper reproduction.",
    "K is a full-trajectory collection proxy, not observed checks before early stopping.",
    "Mean K times mean L ignores unknown correlation; actual prefix sums may be much larger.",
    "Probe passes=2 budgets two complete collections; upstream instead stops each policy early.",
    "Probe passes=1 assumes shared deterministic probes; shared-cache execution is NOT implemented.",
    "Two policy final-answer requests per trajectory are budgeted, even if no early stop occurs.",
    "Forced-answer fraction/output are assumptions: upstream only forces near-budget traces,",
    "and uses a variable remaining-token budget, potentially much greater than 30 or 50 tokens.",
    "Paper Vanilla length is a proxy for base rollout length, not raw API billing metadata.",
    "No provider prefix-cache discounts are assumed; tokenizer/template changes alter input sizes.",
    "Exact-model, raw-prefix, greedy-token-probability and context-limit compatibility is unverified.",
]


def estimate(n, length, steps, args):
    p, h = args.prompt_tokens, args.appended_prompt_tokens
    prefix = p + args.prefix_fraction * length + h
    inputs = n * (p + args.forced_answer_fraction * (p + length + h)
                  + (args.probe_passes * steps + 2) * prefix)
    outputs = n * (length + args.forced_answer_fraction * args.forced_answer_output
                   + args.probe_passes * steps * args.probe_output
                   + 2 * args.final_output)
    return {
        "input_million_tokens": inputs / 1e6,
        "output_million_tokens": outputs / 1e6,
        "token_cost_cny": (inputs * args.input_price_cny
                           + outputs * args.output_price_cny) / 1e6,
        "expected_requests_proxy": n * (3 + args.forced_answer_fraction
                                        + args.probe_passes * steps),
    }


def display(row):
    return {key: round(value, 6) for key, value in row.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", "--models", nargs="+", choices=PAPER, default=list(PAPER))
    parser.add_argument("--scope", choices=["math500", "main4"], default="math500")
    parser.add_argument("--input-price-cny", type=float, required=True)
    parser.add_argument("--output-price-cny", type=float, required=True)
    parser.add_argument("--prefix-fraction", type=float, default=0.5)
    parser.add_argument("--probe-passes", type=int, choices=[1, 2], default=2)
    parser.add_argument("--probe-output", type=float, default=21)
    parser.add_argument("--final-output", type=float, default=30)
    parser.add_argument("--forced-answer-fraction", type=float, default=1)
    parser.add_argument("--forced-answer-output", type=float, default=30)
    parser.add_argument("--prompt-tokens", type=float, default=500)
    parser.add_argument("--appended-prompt-tokens", type=float, default=20)
    args = parser.parse_args()
    for key, value in vars(args).items():
        if isinstance(value, (int, float)) and (not math.isfinite(value) or value < 0):
            parser.error(f"{key} must be finite and nonnegative")
    if args.prefix_fraction > 1 or args.forced_answer_fraction > 1:
        parser.error("prefix-fraction and forced-answer-fraction must be in [0, 1]")
    if len(set(args.model)) != len(args.model):
        parser.error("Duplicate models would double-count costs")
    benchmarks = ["math500"] if args.scope == "math500" else list(TRAJECTORIES)
    models, grand_total = {}, {}
    for model in args.model:
        rows, total = {}, {}
        for benchmark in benchmarks:
            length, steps = PAPER[model][benchmark]
            row = estimate(TRAJECTORIES[benchmark], length, steps, args)
            if not all(math.isfinite(value) for value in row.values()):
                parser.error("Parameters produced non-finite totals; choose smaller values")
            rows[benchmark] = {"trajectories": TRAJECTORIES[benchmark],
                               "mean_output_tokens": length, "mean_steps": steps,
                               **display(row)}
            for key, value in row.items():
                total[key] = total.get(key, 0) + value
                grand_total[key] = grand_total.get(key, 0) + value
        models[model] = {"benchmarks": rows, "total": display(total)}
    print(json.dumps({
        "status": "offline_planning_scenario_not_measured",
        "source": SOURCE, "source_tables": [1, 3], "assumptions": vars(args),
        "warnings": WARNINGS,
        "excluded": ["AMC23 calibration", "judging", "retries", "other baselines",
                     "ablations", "API compatibility testing", "payment fees",
                     "electricity", "labor", "storage", "GPU rental"],
        "models": models, "total": display(grand_total),
    }, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
