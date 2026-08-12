# Kaggriculture — start-here brief for the next session

**Written:** 2026-08-12 · **Branch:** `KA-agent` · **HEAD:** (Phase 7 commit, see `git log`)

Open this in a fresh chat and say *"read NEXT_SESSION.md and start Phase 8."*
Everything needed to resume is here or linked from here.

---

## 0. The one question first: should I submit `main.py`?

**Yes — this is the first behavioral change since the 506.1 submission.**

Phase 7 shipped quadrant zoning (`QUAD_BONUS=2.0`, on by default), measured at
+$4.5k mean margin and 78% winrate over 128 games against the pre-Phase-7
build. This is not a no-op like the last session's fertilizer engine was.

Pre-flight checks:

| Check | Result |
|---|---|
| `agent` is the last callable in the file | ✅ |
| Signature is `agent(obs)` | ✅ |
| Runs clean vs `pass` | ✅ $79,896 mean, 32/32 |
| Stdlib only, self-contained | ✅ |
| `KAG_DEBUG=1` run — no hidden exceptions | ✅ |

**Recommendation: submit now**, then keep working — submissions are scarce
but this one has a measured gain behind it, unlike the last idle one.

---

## 1. State of the repo

Working tree: Phase 7 changes are in `main.py`, `PROJECT_STATUS.md`. Check
`git status` and `git log origin/KA-agent..HEAD` before assuming what's pushed.

### Measured performance (current HEAD, `QUAD_BONUS=2.0`)

| Matchup | Games | Ours | Opponent |
|---|---|---|---|
| vs `pass` | 64 | $79,896 | $3,000 |
| vs `baselines/v12.py` | 64 (swap) | $70,914 | $2,703 |
| vs pre-Phase-7 build (frozen HEAD) | 128 (swap) | $55,575 | $51,044 |

Previous session's numbers for the same matchups were $77,366 / $70,431 /
(the pre-`OPP_SUPPLY` build test, not directly comparable) — Phase 7 improved
or held flat everywhere it was checked, no regression found.

**Quote the self-play/frozen-HEAD number, not the `pass` number**, per the
same logic as last session: `pass` doesn't compete for the market.

---

## 2. What Phase 7 did — cut the walking

`actions.py` had shown 48.3% MOVE + 19.4% PASS. Two levers were tried.

### ❌ Tried and parked: exact-job hysteresis (`STICKY`, default 0.0)

A score bonus for continuing toward the *exact* job a unit was walking to
last turn (optionally gated to only the last 2 steps — "almost there").
Replicated on 3 independent seed sets: a consistent **loss**, roughly −$7k to
−$12k at `STICKY=1.0`. Action-count profiling showed almost no change in
MOVE/PASS share, so the loss wasn't from extra walking — pinning a unit to a
job with decaying relative value cost more in missed better options than it
saved in avoided switching.

Left in the code, verified as an exact no-op at the default. Don't re-try the
same mechanism without a new idea for why it would work this time.

### ✅ Shipped: quadrant zoning (`QUAD_BONUS`, default 2.0)

Each unit gets a "home" quadrant — `unlocked[idx % len(unlocked)]`, a pure
function of unit index and the unlocked-quadrant list. No memory required,
so it can't go stale across the fact that **hands are wiped and rehired every
single morning** (this is why the hysteresis approach above needed careful
index-staleness handling and this one sidesteps it entirely).

Jobs in a unit's home quadrant get a `1 + QUAD_BONUS` score multiplier in the
`value / (distance + 1)` ranking, so the crew spreads out instead of
converging on whichever single job scores highest globally. Swept 0.1 → 5.0;
plateaus from ~2.0 (81–86% winrate in every seed set tried past that point).

Mechanism, confirmed via `actions.py` before/after: PASS dropped 21.6% →
16.2%, and every productive action (WATER, PLANT, HARVEST, DIG) rose. It
converts idle turns into work — it does not reduce total MOVE count (MOVE
share actually rose slightly, 47.3% → 50.6%), it just makes the walking that
does happen pay off more often instead of ending in a stolen job and a PASS.

### Also checked: the "locked-spawn bug" from last session's brief

**Not a bug.** Read `kaggriculture.py`: movement onto `LOCKED` tiles is
explicitly allowed, and shed operations (`DROP`/`PICKUP`) resolve *before*
the `LOCKED` guard specifically so a hand spawned on a locked shed-access tile
isn't stranded. Nothing to design around here — cross this off permanently.

---

## 3. Remaining work, in the order I'd do it

### 🔜 Phase 8 — Re-derive cow and sheep  ← **START HERE**

The analysis was already done two sessions ago. **The comment at
`main.py:80` — *"Only GOOSE is worth the tiles"* — judges on the wrong
metric** (lifetime market cap, not action cost):

| | cost | productions | units | $ per action |
|---|---|---|---|---|
| Goose | $300 | 25 | 50 | **$26** |
| Cow | $400 | 11 | 22 | **$50** |
| Sheep | $500 | 8 | 16 | **$49** |

Cow and sheep produce on 2–3 day intervals instead of daily — roughly 2× the
goose's action-efficiency. Ceiling is ~$10.5k combined across ~8 tiles.

**This was deliberately deferred to after Phase 7** because Phase 7 changes
the action-cost structure the whole comparison rests on — re-measure with
`QUAD_BONUS=2.0` in place, not against the old numbers above.

Build cost is real: `ANIMALS` only knows `GOOSE`. Needs a `PASTURE`
structure, `BUILD_PASTURE`, and generalising the goose-specific valuation
(`goose_value`, `new_goose_value`, `free_coops`, `shed_geese`) — roughly a
150-line refactor.

### Phase 9 — Fix the panic-dump rule *(live bug, not an enhancement)*

When `shed_fill + incoming > SHED_CAP - 10`, `reserve_frac` drops to `0.05`
and the agent sells **anything at almost any price**. Traces showed melon
dumped at **$4** against a $250 base.

Overflow really is discarded, so the rule is right in principle — but it
should dump the **cheapest** items, not everything. This can fire *without*
geese whenever crop throughput is high, so it is probably costing money right
now. Small, self-contained, worth doing even if the phases slip.

### Phase 10 — Land timing

Quadrants 3 and 4 land around **day 11** because cash is tied up in melon
seeds until the day-10 harvest. Reserving toward the next land price is
probably worth several thousand.

### Housekeeping

- `debug_wrapper.py` is redundant with `actions.py` / `trace.py`. Delete
  whenever.

---

## 4. How to run things

```bash
# Paired seeded benchmark. --swap cancels seat advantage. Ties are NOT wins.
.venv/bin/python bench.py --agent main.py --opp pass -n 32 --swap --seed0 1000
.venv/bin/python bench.py --agent main.py --opp baselines/v12.py -n 32 --swap

# Regression vs a frozen previous commit
git show <commit>:main.py > /tmp/prev.py
.venv/bin/python bench.py --agent main.py --opp /tmp/prev.py -n 64 --swap

# Sweep one parameter (against `pass` by default — see trap #3, prefer
# TUNE_OPP=/path/to/frozen/prev.py for anything you actually intend to ship)
.venv/bin/python tune.py MOVE_COST 3,5,7,9,11 -n 32
TUNE_OPP=/tmp/prev.py .venv/bin/python tune.py QUAD_BONUS 1.0 2.0 3.0

# Where the time goes
.venv/bin/python actions.py

# Day-by-day trace of one game
.venv/bin/python trace.py
```

**Every constant is an env var.** `_tune("NAME", default)` reads `KAG_NAME`.
Sweep without editing the file. `KAG_DEBUG=1` disables the try/except so
exceptions actually surface instead of silently returning no-ops.

Engine source of truth — read it rather than guessing at semantics:
```
.venv/lib/python3.13/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py
```

Submitting:
```bash
kaggle competitions submit kaggriculture -f main.py -m "message"
kaggle competitions episodes <SUBMISSION_ID> -v
kaggle competitions replay <EPISODE_ID>
```

---

## 5. Traps this project has already fallen into

Read these before running an experiment. Each one cost real time.

1. **Replicate before you believe a sweep.** `OPP_SUPPLY=0.25` led sweep 1 at
   **81%** and went **negative** on fresh seeds. Always re-run the *whole
   curve* on an independent seed set, not just the winners. (Phase 7's
   `STICKY` also looked plausible on paper and lost on replication —
   replicating isn't optional even when the mechanism sounds right.)

2. **A deterministic agent vs a copy of itself ties exactly.** Mirror matches
   show ~6–20% "winrate" — that is the **neutral** result, not a loss. Don't
   panic at it, and don't cite it as evidence of anything.

3. **`pass` is not an opponent.** It flatters everything, because nothing
   competes for the market. Tune and verify against a frozen real build.

4. **Value harvests at marginal revenue, not sticker price.** The first
   fertilizer cut lost **$22k** by pricing extra units at `price_of(crop)`.
   Going through `batch_revenue(crop, start_inventory(crop, 3), n)` recovered
   $13.5k of it. Prices move as you sell — always price the batch.

5. **Buy per *carrier*, not per opportunity.** Fertilizer bought one sack per
   profitable tile; capping at `1 + len(hands)` was worth $2.6k.

6. **Guess less, profile more.** A guess that fertilizer's loss was action
   cost was wrong (`actions.py` showed it was 2.5% of unit-actions). A guess
   that `STICKY`'s loss *was* about action cost was also wrong — profiling
   showed near-identical MOVE/PASS share with and without it; the loss was in
   which specific jobs got picked, not how much walking happened.

7. **Nothing callable may be defined below `agent`** in `main.py`. Kaggle's
   loader runs the *last* callable in the file.

8. **`OPP_SUPPLY=1.0` is a trade, not a free win.** It costs $4.8k against the
   weak-supplier `v12` baseline. Still the right call — 99/128 vs a real
   competitor — but don't describe it as a strict improvement.

9. **Persistent state must survive daily resets, not just episode resets.**
   Hands are wiped and rehired every morning, so a unit index doesn't mean
   the same physical unit two days running. A stateful scheme keyed on unit
   index (tried for `STICKY`) needs care about what goes stale; a stateless
   one (used for `QUAD_BONUS`) sidesteps the problem entirely. Prefer
   stateless when the data needed is cheap to recompute every turn.

---

## 6. Where the deeper docs are

| File | What's in it |
|---|---|
| `PROJECT_STATUS.md` | **Source of truth.** Full experiment log, every result. |
| `PROJECT_STATUS.html` | Same, formatted and self-contained — **stale as of Phase 7, re-render if needed.** |
| `kaggriculture_handoff.md` | Deep technical handoff — engine facts, design rationale. |
| `CODE_GUIDE.pdf` / `.html` | Every `.py` file explained, 13 pages — **stale as of Phase 7.** |
| `README.md` | The full rulebook — crop/animal tables, price functions, buildings. |
| `AGENTS.md` | Kaggle submission and replay mechanics. |

---

## 7. Suggested opening message for the new chat

> Read `NEXT_SESSION.md`. Start Phase 8 — re-derive cow and sheep against
> the Phase 7 action-cost structure (`QUAD_BONUS=2.0`), not the old numbers.
> Measure with a paired swap benchmark against the current HEAD before
> keeping any change.
