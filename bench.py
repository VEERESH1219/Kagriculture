"""Parallel, seeded benchmark harness for Kaggriculture agents.

Usage:
    uv run bench.py                        # current agent vs random, 32 seeds
    uv run bench.py --opp starter -n 32
    uv run bench.py --agent main:agent --opp baselines/v12.py -n 32
"""

import argparse
import importlib
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor


def _resolve(spec):
    """"main:agent" -> callable; "path/to/file.py" -> path (kaggle loads it);
    "random"/"starter"/"pass" -> builtin name."""
    if spec in ("random", "starter", "pass"):
        return spec
    if ":" in spec:
        mod, fn = spec.split(":", 1)
        return getattr(importlib.import_module(mod), fn)
    return spec


def _play(args):
    seed, a_spec, b_spec, swap = args
    from kaggle_environments import make

    a = _resolve(a_spec)
    b = _resolve(b_spec)
    env = make("kaggriculture", configuration={"seed": seed})
    players = [b, a] if swap else [a, b]
    env.run(players)
    final = env.steps[-1]
    me = 1 if swap else 0
    opp = 0 if swap else 1
    return final[me].reward, final[opp].reward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="main:agent")
    ap.add_argument("--opp", default="random")
    ap.add_argument("-n", "--games", type=int, default=32)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--swap", action="store_true", help="also play seats swapped")
    args = ap.parse_args()

    jobs = [(args.seed0 + i, args.agent, args.opp, False) for i in range(args.games)]
    if args.swap:
        jobs += [(args.seed0 + i, args.agent, args.opp, True) for i in range(args.games)]

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_play, jobs))

    mine = [r[0] for r in results]
    theirs = [r[1] for r in results]
    wins = sum(1 for m, t in zip(mine, theirs) if m > t)

    print(f"{args.agent} vs {args.opp}   ({len(results)} games)")
    print(f"  mean   ${statistics.mean(mine):>12,.0f}   (opp ${statistics.mean(theirs):>10,.0f})")
    print(f"  median ${statistics.median(mine):>12,.0f}")
    print(f"  min    ${min(mine):>12,.0f}")
    print(f"  max    ${max(mine):>12,.0f}")
    if len(mine) > 1:
        print(f"  stdev  ${statistics.stdev(mine):>12,.0f}")
    print(f"  winrate {wins}/{len(results)} = {wins / len(results):.0%}")
    return mine


if __name__ == "__main__":
    sys.exit(0 if main() else 0)
