"""Batch experiment harness: evaluate many configs against HEAD_728 in one pool.

Each config is baked into its own agent file (its `_tune` returns baked values
and ignores the environment), so configs never contaminate each other and every
(config, seed, seat) job can share a single process pool. That is much faster
than one `bench.py` subprocess per config, which is what made the earlier
sweeps take ~2 minutes per point.

    python experiment.py phase2      # one variable at a time
    python experiment.py phase3      # combinations
    python experiment.py custom '{"MAX_ANIMALS":12,"MAX_UNITS":14}'
"""

import itertools
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("EXP_DIR", "/tmp/kag_exp")
BASE = os.path.join(WORK, "HEAD_728.py")

LIVE_TUNE = '''def _tune(name, default):
    raw = os.environ.get("KAG_" + name)
    return type(default)(raw) if raw is not None else default'''


def bake(src_text, overrides, out_path):
    """Write an agent whose tunables are fixed at `overrides` (env ignored)."""
    baked = ("_BAKED = " + repr(overrides) + "\n\n\n"
             "def _tune(name, default):\n"
             "    return _BAKED.get(name, default)")
    text = src_text.replace(LIVE_TUNE, baked, 1)
    if "_BAKED" not in text:
        raise SystemExit("could not bake: _tune definition not found")
    with open(out_path, "w") as fh:
        fh.write(text)
    return out_path


def _play(job):
    a_path, b_path, seed, swap = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"seed": seed})
    players = [b_path, a_path] if swap else [a_path, b_path]
    env.run(players)
    f = env.steps[-1]
    me, opp = (1, 0) if swap else (0, 1)
    return f[me].reward, f[opp].reward


def evaluate(configs, games, seed0, workers=16):
    """configs: list of (label, overrides). Returns list of result dicts."""
    os.makedirs(WORK, exist_ok=True)
    src = open(os.path.join(HERE, "main.py")).read()
    bake(src, {}, BASE)

    paths = {}
    for label, ov in configs:
        safe = label.replace("=", "").replace(",", "_").replace(" ", "").replace(".", "p")
        paths[label] = bake(src, ov, os.path.join(WORK, f"cfg_{safe}.py"))

    jobs, index = [], []
    for label, _ in configs:
        for i in range(games):
            for swap in (False, True):
                jobs.append((paths[label], BASE, seed0 + i, swap))
                index.append(label)

    with ProcessPoolExecutor(max_workers=workers) as ex:
        raw = list(ex.map(_play, jobs, chunksize=1))

    out = []
    for label, _ in configs:
        mine = [r[0] for r, l in zip(raw, index) if l == label]
        theirs = [r[1] for r, l in zip(raw, index) if l == label]
        wins = sum(1 for a, b in zip(mine, theirs) if a > b)
        out.append({
            "label": label,
            "n": len(mine),
            "mean": statistics.mean(mine),
            "margin": statistics.mean(mine) - statistics.mean(theirs),
            "winrate": wins / len(mine),
            "min": min(mine),
            "max": max(mine),
        })
    return out


def report(results, title):
    print(f"\n=== {title} ===")
    print(f"{'config':>34} {'n':>4} {'mean':>10} {'margin':>9} {'win':>6} "
          f"{'min':>9} {'max':>10}")
    for r in sorted(results, key=lambda r: -r["margin"]):
        print(f"{r['label']:>34} {r['n']:>4} ${r['mean']:>9,.0f} "
              f"{r['margin']:>+9,.0f} {r['winrate']:>6.0%} "
              f"${r['min']:>8,.0f} ${r['max']:>9,.0f}")


PHASE2 = (
    [(f"MAX_ANIMALS={v}", {"MAX_ANIMALS": v}) for v in (12, 14)]
    + [(f"MAX_UNITS={v}", {"MAX_UNITS": v}) for v in (14, 16)]
    + [(f"ANIMALS_PER_UNIT={v}", {"ANIMALS_PER_UNIT": v}) for v in (2.25, 2.5)]
    + [(f"RESERVE_FRAC={v}", {"RESERVE_FRAC": v}) for v in (0.30, 0.20, 0.10)]
    + [(f"OPP_SUPPLY={v}", {"OPP_SUPPLY": v}) for v in (0.50, 0.75, 1.25)]
    + [(f"QUAD_BONUS={v}", {"QUAD_BONUS": v}) for v in (1.5, 2.5, 3.0)]
)

# A/B/C are the requested candidates. Their MAX_UNITS component is inert at
# current land (Phase 2: target_units is tile-capped at 9), so they mostly
# measure MAX_ANIMALS/RESERVE_FRAC/OPP_SUPPLY.
#
# D-H unlock the tile term first -- more land and/or a lower TILES_PER_UNIT --
# so the crew and flock caps can actually bind. That is the combination
# single-parameter sweeps structurally cannot reach: Phase 11 moved land alone
# and lost, Phase 12 moved crew alone and lost.
PHASE3 = [
    ("A:u14,a12,r.30,o.75", {"MAX_UNITS": 14, "MAX_ANIMALS": 12,
                             "ANIMALS_PER_UNIT": 2.0, "RESERVE_FRAC": 0.30,
                             "OPP_SUPPLY": 0.75, "QUAD_BONUS": 2.0}),
    ("B:u14,a14,r.30,o.75", {"MAX_UNITS": 14, "MAX_ANIMALS": 14,
                             "ANIMALS_PER_UNIT": 2.0, "RESERVE_FRAC": 0.30,
                             "OPP_SUPPLY": 0.75, "QUAD_BONUS": 2.0}),
    ("C:u16,a14,r.20,o.75", {"MAX_UNITS": 16, "MAX_ANIMALS": 14,
                             "ANIMALS_PER_UNIT": 2.0, "RESERVE_FRAC": 0.20,
                             "OPP_SUPPLY": 0.75, "QUAD_BONUS": 2.0}),
    ("D:land2,tpu4,a14,u16,r.20", {"MAX_LAND_BUYS": 2, "TILES_PER_UNIT": 4.0,
                                   "MAX_ANIMALS": 14, "MAX_UNITS": 16,
                                   "RESERVE_FRAC": 0.20}),
    ("E:land2,tpu4,a12,u14,r.20,o.75", {"MAX_LAND_BUYS": 2, "TILES_PER_UNIT": 4.0,
                                        "MAX_ANIMALS": 12, "MAX_UNITS": 14,
                                        "RESERVE_FRAC": 0.20, "OPP_SUPPLY": 0.75}),
    ("F:land2,tpu5,a12,u14,r.30", {"MAX_LAND_BUYS": 2, "TILES_PER_UNIT": 5.0,
                                   "MAX_ANIMALS": 12, "MAX_UNITS": 14,
                                   "RESERVE_FRAC": 0.30}),
    ("G:land3,tpu4,a16,u16,r.20", {"MAX_LAND_BUYS": 3, "TILES_PER_UNIT": 4.0,
                                   "MAX_ANIMALS": 16, "MAX_UNITS": 16,
                                   "RESERVE_FRAC": 0.20}),
    ("H:tpu4,u16,a12,r.20", {"TILES_PER_UNIT": 4.0, "MAX_UNITS": 16,
                             "MAX_ANIMALS": 12, "RESERVE_FRAC": 0.20}),
    ("I:best-singles", {"OPP_SUPPLY": 1.25, "RESERVE_FRAC": 0.20,
                        "QUAD_BONUS": 1.5}),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "phase2"
    games = int(os.environ.get("EXP_GAMES", 24))
    seed0 = int(os.environ.get("EXP_SEED0", 1000))
    if mode == "phase2":
        cfgs = PHASE2
    elif mode == "phase3":
        cfgs = PHASE3
    elif mode == "custom":
        ov = json.loads(sys.argv[2])
        cfgs = [(sys.argv[3] if len(sys.argv) > 3 else "custom", ov)]
    else:
        raise SystemExit(f"unknown mode {mode}")
    res = evaluate(cfgs, games, seed0)
    report(res, f"{mode}  vs HEAD_728  ({games * 2} games/config, seed0={seed0})")


main()
