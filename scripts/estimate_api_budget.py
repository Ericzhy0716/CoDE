#!/usr/bin/env python3
"""Offline budget scenarios for shared-rollout Vanilla/DEER/CoDE replay.

No network, credentials, inference, or measured-throughput claims. Prices must
be supplied in CNY per million tokens; see docs/API_TOKEN_BUDGET_20260921.md.
"""

import argparse
import json
import math


BASE_OUTPUT_TOKENS = {
    "qwen3-4b": {"math500": 5_210_000, "main4": 32_385_654},
    "qwen3-14b": {"math500": 4_878_000, "main4": 29_063_922},
    "deepseek-r1-distill-llama-8b": {
        "math500": 4_576_000,
        "main4": 29_103_090,
    },
}
TRAJECTORIES = {"math500": 1_000, "main4": 4_209}


def estimate(n, mean_length, checks, input_price, output_price,
             prompt_tokens=500, prefix_fraction=0.5):
    # One base rollout, one full-prefix forced answer, and two stopping policies.
    policies, probe_output, final_output, appended_prompt = 2, 21, 30, 20
    prefix_input = prompt_tokens + mean_length * prefix_fraction + appended_prompt
    inputs = n * (
        prompt_tokens + prompt_tokens + mean_length + appended_prompt
        + policies * (checks + 1) * prefix_input
    )
    outputs = n * (
        mean_length + final_output
        + policies * (checks * probe_output + final_output)
    )
    return {
        "checks_per_policy_per_trajectory": checks,
        "input_million_tokens": round(inputs / 1e6, 6),
        "output_million_tokens": round(outputs / 1e6, 6),
        "requests_before_retries_and_judging": n * (2 * checks + 4),
        "token_cost_cny": round((inputs * input_price + outputs * output_price) / 1e6, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=BASE_OUTPUT_TOKENS, required=True)
    parser.add_argument("--scope", choices=TRAJECTORIES, default="math500")
    parser.add_argument("--input-price-cny", type=float, required=True)
    parser.add_argument("--output-price-cny", type=float, required=True)
    parser.add_argument("--checks", nargs="+", type=int, default=[5, 20, 100])
    parser.add_argument("--prompt-tokens", type=int, default=500)
    parser.add_argument("--prefix-fraction", type=float, default=0.5)
    parser.add_argument("--gpu-hourly-prices", nargs="+", type=float,
                        help="Optional CNY/hour rates for pure-cost break-even hours; not a memory/compatibility check.")
    args = parser.parse_args()
    if not all(math.isfinite(v) for v in [args.input_price_cny,
                                          args.output_price_cny,
                                          args.prefix_fraction]):
        parser.error("Prices and prefix fraction must be finite.")
    if min(args.input_price_cny, args.output_price_cny, args.prompt_tokens) < 0:
        parser.error("Prices and prompt length must be nonnegative.")
    if any(k < 0 for k in args.checks) or not 0 <= args.prefix_fraction <= 1:
        parser.error("Checks must be nonnegative; prefix fraction must be in [0, 1].")
    if args.gpu_hourly_prices and any(not math.isfinite(p) or p <= 0
                                     for p in args.gpu_hourly_prices):
        parser.error("GPU hourly prices must be finite and positive.")
    n = TRAJECTORIES[args.scope]
    mean_length = BASE_OUTPUT_TOKENS[args.model][args.scope] / n
    scenarios = [estimate(n, mean_length, k, args.input_price_cny,
                          args.output_price_cny, args.prompt_tokens,
                          args.prefix_fraction) for k in args.checks]
    if args.gpu_hourly_prices:
        for scenario in scenarios:
            cost = (scenario["input_million_tokens"] * args.input_price_cny
                    + scenario["output_million_tokens"] * args.output_price_cny)
            scenario["gpu_break_even"] = [
                {"hourly_price_cny": p, "billed_hours": round(cost / p, 3)}
                for p in args.gpu_hourly_prices
            ]
    print(json.dumps({
        "status": "planning_scenario_not_measured_or_compatibility_verified",
        "assumptions": vars(args),
        "trajectories": n,
        "base_output_million_tokens": n * mean_length / 1e6,
        "excluded": ["AMC calibration", "judging", "retries", "other ablations",
                     "payment fees", "electricity", "labor"],
        "scenarios": scenarios,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
