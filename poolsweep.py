"""Sweep a tunable against the calibrated opponent pool.

`sweep.py` scores a change against ONE frozen opponent (a copy of ourselves).
That metric gave Phase 11 a 91% winrate and Phase 13 an 83% winrate, and
neither moved the real leaderboard. `pool.py --calibrate` showed the varied
pool reproduces real leaderboard ordering (Spearman +0.900), so pool winrate
is the metric a change has to move before it earns a submission.

Every pool opponent is env-immune -- `pass` is a builtin, `baselines/v12.py`
reads no environment, and git-ref builds go through `freeze.py` -- so a
`KAG_*` override here changes our side only.

    python poolsweep.py QUAD_BONUS 1.0 2.0 3.0
    python poolsweep.py -n 6 OPP_SUPPLY 0.5 1.0 1.5
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(overrides, games, seed0):
    env = dict(os.environ)
    for k, v in overrides.items():
        env["KAG_" + k] = str(v)
    out = subprocess.run(
        [sys.executable, "pool.py", "-n", str(games), "--seed0", str(seed0)],
        capture_output=True, text=True, env=env, cwd=HERE,
    )
    m = re.search(r"POOL winrate\s+([\d.]+)%\s+POOL mean margin\s+([+-][\d,]+)", out.stdout)
    if not m:
        print(out.stdout, out.stderr, file=sys.stderr)
        return None
    return float(m.group(1)), float(m.group(2).replace(",", "").replace("+", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--games", type=int, default=6, help="seeds per opponent (x2 seats)")
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("name")
    ap.add_argument("values", nargs="+")
    args = ap.parse_args()

    print(f"pool sweep: {args.name}   ({args.games * 2} games x 9 opponents per point)\n")
    base = run({}, args.games, args.seed0)
    print(f"{'baseline':>18}   pool winrate {base[0]:>6.1f}%   margin {base[1]:>+10,.0f}")
    best = (base[0], "baseline")
    for v in args.values:
        r = run({args.name: v}, args.games, args.seed0)
        if r is None:
            continue
        flag = ""
        if r[0] > best[0]:
            best = (r[0], v)
            flag = "  <-- best so far"
        print(f"{args.name + '=' + str(v):>18}   pool winrate {r[0]:>6.1f}%   "
              f"margin {r[1]:>+10,.0f}   {r[0] - base[0]:+.1f}pp{flag}")
    print(f"\nbest: {best[1]}  ({best[0]:.1f}% pool winrate)")


main()
