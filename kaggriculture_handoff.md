# Kaggriculture Agent — Handoff

State as of the v13 rewrite. Every number below was measured with `bench.py`
over fixed seeds, not estimated.

## Current performance

| Matchup | Games | Mean | Median | Min | Winrate |
|---|---|---|---|---|---|
| vs `random` | 16 | **$81,166** | $80,938 | $72,201 | 16/16 |
| vs `pass` (deterministic, used for tuning) | 48 | $78,475 | $79,689 | $48,171 | 48/48 |
| vs old **v12** agent, both seats | 20 | **$74,635** | $73,885 | $55,793 | 20/20 |
| **self-play**, both seats | 16 | **$43,841** | $44,334 | $23,881 | n/a — mirror |

**The self-play row is the only contested-market number, and it is the one to
trust.** Every other opponent barely sells, so we alone drain the town and take
every scarcity premium. Against a real competitor the score falls **44%**. Do
not quote $78k as an expected result.

Its winrate is meaningless: the agent is deterministic, so against a copy of
itself it mirrors exactly and ties on ~2/3 of seeds; `bench.py` counts a tie as
a non-win and prints `3/16`. Verified per-seed — 1000, 1001, 1002 and 1004 are
exact ties to the dollar; 1003 and 1005 diverge.

Previous v12 baseline: **$4,464** mean vs `random`. Current agent is ~18x that.
Runtime is 4.6 ms/turn against a 1000 ms `actTimeout`, so there is a lot of
compute headroom left.

The gain over the v13 numbers is **mid-day porter runs** (`PORTER_FILL`), paired
over 48 seeds vs `pass`: $78,475 with, $76,273 without — **+$2,202 mean, +$3,186
median, +$4,624 on the minimum**. It helps the floor more than the mean because
it bites exactly in the games where a day's production outruns the 100-item shed
and the surplus was being discarded at end of day. Measure this one at n≥48: at
n=16 the effect flipped sign between seed windows.

## Tooling

- `bench.py` — parallel seeded benchmark. `uv run bench.py --opp pass -n 16 --swap`
- `tune.py` — one-parameter sweep. `uv run tune.py MAX_UNITS 10 12 14`
- `trace.py` — per-day trace of one episode. `uv run trace.py --seed 2003 --opp pass`
- `actions.py` — where the crew's day goes, by op. `uv run actions.py --seed 2003`
- `baselines/v12.py` — frozen old agent, for regression checks.
- `KAG_DEBUG=1` disables `agent`'s try/except so exceptions surface.

`actions.py` is the one to reach for when a change looks economically sound but
does not pay. Movement is over half of every unit-action the agent issues, so a
job that prices well per *action* can still lose once you count the walk to it.

**Always tune against `pass`, not `random`.** The built-in `random_agent` calls
`random.Random()` with no seed, which added ~3.5% run-to-run noise and drowned
real effects.

## Engine facts that drive the design

These came from reading `kaggle_environments/envs/kaggriculture/kaggriculture.py`.
Several contradict the previous handoff.

1. **The last callable wins.** `agent.py:64` does
   `[v for v in env.values() if callable(v)][-1]`. Kaggle runs the last callable
   *defined in the file*, regardless of its name. Nothing may be defined below
   `agent` in `main.py`. (`if __name__ == "__main__"` is dead code on Kaggle —
   the file is exec'd with `env = {}`.)

2. **Locked tiles are walkable.** Movement onto `LOCKED` is explicitly allowed;
   only tile *operations* are rejected. There are no obstacles anywhere, so
   Manhattan distance is exact and BFS buys nothing.

3. **Watering only adds yield inside a window** — `[ceil(max_yield_day/2),
   max_yield_day]`, +1 unit per watering. Outside that window watering does
   nothing except reset the death counter, and *two consecutive* dry end-of-days
   are needed to kill a plant. So outside the window, water every other day.
   Planting day counts as unwatered, so a fresh plant must be watered that day.

4. **Derived optimal plans** (computed in `_build_crop_plans`, verified against
   the engine): WHEAT harvest age 4 → 4 units; CARROT age 3 → 3; MELON age 10 →
   6; TOMATO age 11 → 4; STRAWBERRY age 16 → 4.

5. **Hire cost is `fib(n)` with `mult = 1`, reset daily** — 1,1,2,3,5,8,13,…
   Cheap, but superlinear: 12 units ≈ $233/day, 15 ≈ $986/day, 18 ≈ $4180/day.
   Measured optimum is **12 units total**; 15 cost ~$19k/season for no gain.

6. **The town creates scarcity premiums.** Shops unlock every 3 days (up to 8
   instances, drawn *with replacement*) and consume every 4 turns. Anything
   nobody sells drifts *below* `I0 = 10000`, and its price *rises* all season.
   Strawberry reached $333 (4 of 8 shops demand it) and was the single largest
   earner in most games. Modelling this drawdown was worth ~$2k/game.

7. **Price curves decide crop caps.** `log` decay ≈ uncapped; `sq`/`linear`
   saturate hard.

   | Item | Above-curve | Revenue @300 sold | Verdict |
   |---|---|---|---|
   | WHEAT | log | $6,313 (still $20/unit) | effectively uncapped |
   | EGG | log | $12,559 (still $40/unit) | effectively uncapped |
   | CARROT | sqrt | $6,510 | mid |
   | MELON | sq | $26,627 then **$1 forever** | one-shot ~158 units |
   | STRAWBERRY / MILK / WOOL | linear / sq | tiny | dump-proof only |

   **Melon is in zero shops** — only the town centre's 1/day drains it. It is a
   one-shot $26k prize, not a repeatable engine.

8. **Fertilizer is net-negative.** $100 buys +2 wheat ($50) or +1 carrot ($35).
   Melon already reaches `max_yield` at age 10 unfertilized. Do not reintroduce
   it (the old handoff recommended this; the arithmetic says no).

9. **Shed cap is 100 items**, and end-of-day overflow is **silently discarded**.
   Harvests go to per-unit inventory and only reach the shed at end of day.

10. **The season ends mid-day 29** (`step >= episodeSteps - 2` at step 718), so
    day 29 never gets an end-of-day drop. Anything a unit is still carrying then
    is worth zero — hence the forced `DROP` run in the agent.

## Architecture (`main.py`)

Pure functions on top, `_decide` does the work, `agent` last as a try/except
wrapper. Each turn:

1. **Scan** the farm into empties / weeds / plants, and total our unsold
   `pipeline` per crop (growing + shed + carried).
2. **Value crops.** `crop_profit` prices a new planting at the inventory it will
   *face at harvest*: `today − town_drawdown_over_cycle + our_pipeline`. The
   drawdown term finds scarcity premiums; the pipeline term stops us flooding a
   market.
3. **Rank crops** with `crop_score`, which divides profit by
   `cycle * (1 + seed_cost / cash_per_free_tile)`. This interpolates between
   "maximise return on capital" (day 0: land free, cash scarce — buy $10 wheat,
   never $100 strawberry) and "maximise return on land" (day 15: cash ample).
   This one change was worth **+$3.7k/game**.
4. **Build a job list** priced in dollars — HARVEST, WATER (yield vs survival
   valued separately), DIG, PLANT, DROP, plus the (default-off) flock ops.
   Each job carries a `need` (an item the unit must already hold, e.g. FEED
   needs wheat), an optional `unit` pin, and a `key` naming what two jobs may
   not share this turn. Crop ops key on the tile because they consume it;
   animal ops key on `(tile, op)`, since one coop can be fed, cared for and
   harvested by three different units in the same turn.
5. **Assign** by ranking every (unit, job) pair on `value / (distance + 1)`, so
   a unit prefers a decent job at its feet to a great one across the farm.
   Unit-pinned jobs are placed first and claim their key.
6. **Market orders**, in resolution order: SELL (funds the rest) → BUY_LAND →
   HIRE → BUY_ANIMAL → BUY_PRODUCT (feed) → BUY_SEED.

Two invariants worth preserving:

- **Never queue more `PLANT` ops for a crop than seeds held.** The engine drops
  *all* of that crop's plants for the turn if you overcommit. The crop is chosen
  at execution time from a decrementing counter.
- **Never plant beyond `crew * PLANTS_PER_UNIT`.** An unwatered plant is not
  just a lost seed, it becomes a weed that costs a DIG.

## Tuned parameters

Swept one at a time vs `pass`, 16 seeds. Current values in `main.py`:

| Param | Value | Notes |
|---|---|---|
| `MAX_UNITS` | 12 | 8→$66k, 10→$69k, **12→$69k**, 14→$63k |
| `TILES_PER_UNIT` | 6.0 | 5→$48k (over-hires), 6→$71k, 8→$66k |
| `MOVE_COST` | 7.0 | flat 3–7; 10→$48k, 15→$46k |
| `SEED_RATION` | 6 | 4→$62k, **6→$77k**, 10→$74k, 20→$68k |
| `LAND_BUFFER` | 800 | 200→$50k (starves seeds); ≥400 all equal |
| `RESERVE_FRAC` | 0.45 | no measurable effect — sell logic rarely binds |
| `PLANTS_PER_UNIT` | 11 | no effect; capacity is not binding at 12 units |
| `PORTER_FILL` | 0.6 | shed fill that starts mid-day drops; +$2,202 vs off (n=48) |
| `MAX_GEESE` | 0 | flock off — see below; 4→−$10k, 8→−$17k, 16→−$25k |

## Next steps, highest expected value first

1. **Land timing.** Quadrants 3 and 4 are still bought around day 11 because
   cash is tied up in melon seeds until the day-10 harvest. Reserving toward the
   next land price, or deferring melon, is probably worth several thousand.
2. **Cut the walking.** `actions.py` says **51.7%** of all unit-actions are
   moves and another 11.5% are `PASS`. Assignment is greedy per turn and has no
   notion of a route, so units criss-cross the farm. Servicing tiles in a sweep,
   or biasing each unit toward a home region, is now the biggest lever on the
   crop engine itself — and it is the precondition for the flock ever paying.
3. **The panic-dump rule may be mispriced.** When `shed_fill + incoming >
   SHED_CAP - 10`, `reserve_frac` drops to 0.05 and the agent sells anything at
   almost any price. In flock traces this dumped melon at **$4** against a base
   of $250. Overflow really is discarded, so the rule is right in principle, but
   it should dump the *cheapest* items rather than everything.
4. **Re-derive the animal question.** `ANIMALS` contains only `GOOSE` — there is
   no cow or sheep path in the agent at all. The comment at `main.py:80` rules
   them out because milk caps at ~$6k lifetime revenue and wool at ~$8k, but
   that was computed **assuming the whole market is ours**. Live Kaggle replays
   show opponents buying cows on day 1. A capped $6k that nobody contests can
   beat an uncapped wheat plan that several agents are collapsing at once.

## `OPP_SUPPLY`: pricing supply we cannot observe (2026-08-11)

`crop_profit` and `start_inventory` price a harvest against
`minv − town_drawdown + pipeline`, and `pipeline` holds **only our own** crop —
the opponent's fields are not in the observation. Both sites now scale it by
`1 + OPP_SUPPLY`. At `0.0` the agent is byte-identical in behaviour to the old
one (verified to the dollar); the shipped default is **`1.0`**, i.e. assume a
symmetric opponent.

Swept 0 → 3 against a frozen copy of the `0.0` agent over **two independent
64-game seed sets** (`--seed0 1000` and `5000`, `--swap` on both):

| OPP_SUPPLY | run 1 | run 2 | combined WR |
|---|---|---|---|
| 0.0 (control) | $0 / 20% | $0 / 17% | 24/128 = 19% |
| 0.25 | +$5,389 / 81% | −$439 / 56% | 88/128 = 69% |
| 0.5 | −$1,801 / 39% | +$1,144 / 59% | 63/128 = 49% |
| 0.75 | +$4,810 / 66% | +$7,085 / 75% | 90/128 = 70% |
| **1.0** | **+$6,115 / 73%** | **+$8,912 / 81%** | **99/128 = 77%** |
| 1.5 | +$4,318 / 77% | +$613 / 62% | 89/128 = 70% |
| 2.0 | +$527 / 44% | +$158 / 48% | 59/128 = 46% |
| 3.0 | −$21,044 / 0% | −$19,886 / 0% | 0/128 = 0% |

Two things to carry forward. **Always replicate on fresh seeds** — `0.25` led
run 1 at 81% and went negative on run 2; a single sweep would have shipped a
no-op. And **`1.0` is a trade, not a free win**: it is flat vs `pass` (+$118)
but costs **$4,761 against v12**, because assuming a symmetric opponent
over-corrects against a weak supplier. It still wins 100% of v12 games, just by
less. Right call against live agents, wrong call against a passive field.

## Phase 4 (goose / egg engine): built, measured, switched off

The husbandry is implemented and works — coops get built, birds bought, fetched
from the shed, placed, fed, cared for, harvested, and their fertilizer
collected. It is behind `MAX_GEESE`, which now **defaults to 0**. It loses money
at every size tried (16 seeds vs `pass`):

| `MAX_GEESE` | 0 | 4 | 8 | 16 |
|---|---|---|---|---|
| mean | **$79,472** | $69,309 | $62,858 | $54,027 |

The previous handoff's case for it — "~$80/tile-day versus wheat's ~$22" — was
arithmetic on *tiles*, and tiles are not the binding constraint; **unit-actions
are**. A goose grosses ~$150/day (2 eggs at ~$42, 1 fertilizer at ~$70, less a
$35 wheat), but collecting that takes FEED + CARE + COLLECT + half a HARVEST,
each on the coop tile itself, with a walk between every one. At ~7 actions/day
per bird, 16 birds eat well over half the crew's day, and traces show it still
only managed to feed 7–11 of 16 birds daily.

Engine facts established while building it, all still true and worth keeping:

- `BUILD_COOP` is **free**; the $300 is the bird. It needs a `None` tile.
- Animals produce **whether or not they are fed**. Feeding matters only for
  survival (two consecutive dry nights and the bird escapes, structure intact)
  and because the CARE bonus is only spent on a *fed* production night.
- `FEED` takes wheat from the **unit's** inventory, not the shed — so every feed
  cycle needs a `PICKUP` run first. This is what makes it so action-hungry.
- `max_held` caps only *uncollected* product, so lifetime output is unbounded.
- **FERTILIZER is in no shop's list and is excluded from the town centre**
  (`TOWN_CENTER_PRODUCTS = [p for p in PRODUCTS if p != "FERTILIZER"]`). Its
  inventory therefore only ever moves when we sell, making it a one-shot
  ~$25k prize (price floors after ~495 units), exactly like melon.
- `BUY_ANIMAL` lands the bird in the **shed**, where it occupies a slot against
  the 100-item cap until a unit fetches it.

If it is revisited, fix the walking first (item 3), then cluster coops into one
adjacent block so a unit can service several birds without crossing the farm.
