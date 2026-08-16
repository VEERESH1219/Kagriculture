"""Benchmark against a varied pool of opponents, and calibrate that pool
against real leaderboard outcomes.

Why this exists
---------------
`bench.py`/`sweep.py` measure one agent against ONE frozen opponent -- almost
always a copy of ourselves. Beating a mirror of your own strategy does not
predict performance against thousands of genuinely different ones, and the
project has now demonstrated that twice:

  Phase 11  broken method,  "+$8.6k / 91%"  -> leaderboard 708.4 -> 686.4
  Phase 13  fixed method,   "+$6.2k / 83%"  -> leaderboard 728.1 -> 721.0

Both were real wins against a self-copy and neither moved the real score.
So the pool here is deliberately heterogeneous: old weak builds, mid-era
builds, the current best, and `pass`. A change has to beat varied strategies,
not one mirror, before it earns a submission.

Every git-ref opponent is passed through `freeze.py` so it ignores `KAG_*`
(see PROJECT_STATUS.md, Phase 13 -- env overrides leak into file opponents
loaded in the same process and silently turn a sweep into a mirror match).

Calibration
-----------
POOL entries carry the real public leaderboard score each build earned, so
`--calibrate` can play every one of them against the pool and check whether
pool ranking reproduces leaderboard ranking (Spearman). A pool that cannot
rank builds we already know the answer for should not be trusted to rank a
new one.

    python pool.py                          # current main.py vs the pool
    python pool.py --agent /tmp/variant.py -n 24
    python pool.py --calibrate              # does the pool predict reality?
"""

import argparse
import itertools
import os
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

# (label, git ref or path, public leaderboard score or None)
# Scores are the settled public score each build earned when submitted; they
# are the ground truth `--calibrate` measures the pool against.
#
# Deduplicated by content hash -- a94f966 ("nogoose", 708.4) and 18a8410
# ("best", 728.1) are byte-identical apart from a comment and a no-op tunable
# whose default is unchanged, so they are ONE strategy. Keeping both would
# double-weight it in the pool. That pair is also this project's cleanest
# measurement of leaderboard noise: the same agent, submitted twice a day
# apart, scored 20 points apart. Treat any gap under ~20 points as unresolved.
POOL = [
    ("pass",        "pass",                None),
    ("v12",         "baselines/v12.py",    None),
    ("rewrite",     "6db7ab8",             None),
    ("oppsupply",   "6f4f1b6",             None),
    ("phase7",      "b11abc5",            630.2),
    ("phase8",      "14bf159",            641.2),
    ("land1",       "fd6808a",            693.7),
    ("best",        "18a8410",            728.1),
    ("phase13",     "cd467b6",            721.0),
]

# Builds used as the *agent* during calibration: every pool entry with a known
# leaderboard score. Each plays the whole pool (minus itself) and we ask
# whether pool result ordering matches leaderboard ordering.
CALIBRATION = [(l, r, s) for l, r, s in POOL if s is not None]


def materialise(ref, workdir):
    """git ref -> frozen file path. Paths and builtins pass through."""
    if ref in ("pass", "random", "starter"):
        return ref
    if ref.endswith(".py"):
        return ref if os.path.isabs(ref) else os.path.join(HERE, ref)
    raw = os.path.join(workdir, f"{ref}_raw.py")
    out = os.path.join(workdir, f"{ref}_frozen.py")
    if not os.path.exists(out):
        with open(raw, "w") as fh:
            subprocess.run(["git", "show", f"{ref}:main.py"], stdout=fh, cwd=HERE, check=True)
        subprocess.run([sys.executable, "freeze.py", raw, out], cwd=HERE, check=True,
                       stdout=subprocess.DEVNULL)
    return out


def _play(job):
    seed, a_spec, b_spec, swap = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"seed": seed})
    players = [b_spec, a_spec] if swap else [a_spec, b_spec]
    env.run(players)
    final = env.steps[-1]
    me, opp = (1, 0) if swap else (0, 1)
    return final[me].reward, final[opp].reward


def versus(agent, opponent, games, seed0, workers):
    """Paired, seat-swapped match. Returns (mean, margin, winrate)."""
    jobs = [(seed0 + i, agent, opponent, sw)
            for i in range(games) for sw in (False, True)]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(_play, jobs))
    mine = [a for a, _ in res]
    theirs = [b for _, b in res]
    wins = sum(1 for a, b in zip(mine, theirs) if a > b)
    return statistics.mean(mine), statistics.mean(mine) - statistics.mean(theirs), wins / len(res)


def run_pool(agent, workdir, games, seed0, workers, skip=None, quiet=False):
    """Play `agent` against every pool entry. Returns (mean_winrate, mean_margin)."""
    wrs, margins = [], []
    for label, ref, _ in POOL:
        if skip and label == skip:
            continue
        opp = materialise(ref, workdir)
        mean, margin, wr = versus(agent, opp, games, seed0, workers)
        wrs.append(wr)
        margins.append(margin)
        if not quiet:
            print(f"  {label:>10}  ${mean:>10,.0f}   {margin:>+9,.0f}   {wr:>6.0%}")
    return statistics.mean(wrs), statistics.mean(margins)


def spearman(xs, ys):
    """Rank correlation, no scipy."""
    def ranks(vs):
        order = sorted(range(len(vs)), key=lambda i: vs[i])
        r = [0.0] * len(vs)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d2 / (n * (n * n - 1))


def calibrate(workdir, games, seed0, workers):
    print("Calibration -- can the pool reproduce known leaderboard ordering?\n")
    rows = []
    for label, ref, lb in CALIBRATION:
        agent = materialise(ref, workdir)
        wr, margin = run_pool(agent, workdir, games, seed0, workers, skip=label, quiet=True)
        rows.append((label, lb, wr, margin))
        print(f"  {label:>10}  leaderboard {lb:>7.1f}   pool winrate {wr:>6.1%}   "
              f"pool margin {margin:>+9,.0f}")

    lbs = [r[1] for r in rows]
    print(f"\n  Spearman(leaderboard, pool winrate) = {spearman(lbs, [r[2] for r in rows]):+.3f}")
    print(f"  Spearman(leaderboard, pool margin)  = {spearman(lbs, [r[3] for r in rows]):+.3f}")
    print("\n  +1.0 = pool ranks builds exactly as the leaderboard did (trustworthy).")
    print("   0.0 = pool ordering is unrelated to leaderboard ordering (useless).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="main.py")
    ap.add_argument("-n", "--games", type=int, default=16, help="seeds per opponent (x2 seats)")
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as workdir:
        if args.calibrate:
            calibrate(workdir, args.games, args.seed0, args.workers)
            return
        agent = args.agent if os.path.isabs(args.agent) else os.path.join(HERE, args.agent)
        print(f"{args.agent} vs pool   ({args.games * 2} games per opponent, seed0={args.seed0})\n")
        print(f"  {'opponent':>10}  {'our mean':>11}   {'margin':>9}   {'winrate':>6}")
        wr, margin = run_pool(agent, workdir, args.games, args.seed0, args.workers)
        print(f"\n  POOL winrate {wr:.1%}   POOL mean margin {margin:+,.0f}")


main()
