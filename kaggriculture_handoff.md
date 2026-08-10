# Kaggriculture Agent — Handoff

State as of the v13 rewrite. Every number below was measured with `bench.py`
over fixed seeds, not estimated.

## Current performance

| Matchup | Games | Mean | Median | Min | Winrate |
|---|---|---|---|---|---|
| vs `random` | 16 | **$77,287** | $77,236 | $66,554 | 16/16 |
| vs `pass` (deterministic, used for tuning) | 16 | $74,510 | $75,848 | $62,120 | 16/16 |
| vs old **v12** agent, both seats | 20 | **$65,843** | $68,308 | $39,102 | 20/20 |

Previous v12 baseline: **$4,464** mean vs `random`. Current agent is ~17x that.
Runtime is 4.6 ms/turn against a 1000 ms `actTimeout`, so there is a lot of
compute headroom left.

## Tooling

- `bench.py` — parallel seeded benchmark. `uv run bench.py --opp pass -n 16 --swap`
- `tune.py` — one-parameter sweep. `uv run tune.py MAX_UNITS 10 12 14`
- `trace.py` — per-day trace of one episode. `uv run trace.py --seed 2003 --opp pass`
- `baselines/v12.py` — frozen old agent, for regression checks.
- `KAG_DEBUG=1` disables `agent`'s try/except so exceptions surface.

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
   valued separately), DIG, PLANT, DROP.
5. **Assign** by ranking every (unit, job) pair on `value / (distance + 1)`, so
   a unit prefers a decent job at its feet to a great one across the farm.
6. **Market orders**, in resolution order: SELL (funds the rest) → BUY_LAND →
   HIRE → BUY_SEED.

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

## Next steps, highest expected value first

1. **Goose / egg engine (Phase 4, not started).** EGG is `log`-priced and
   effectively uncapped at ~$40. `FEED` + `CARE` yields **2 eggs/day/tile**
   indefinitely (`max_held` caps unharvested product, not lifetime output),
   costing 1 wheat/day. That is ~$80/tile-day versus wheat's ~$22 — second only
   to melon, and unlike melon it does not saturate. Needs: `BUILD_COOP`,
   `BUY_ANIMAL`, `PICKUP` at shed, `PLACE`, then daily FEED/CARE/HARVEST plus
   `COLLECT_FERTILIZER`. This is the largest single remaining lever.
2. **Land timing.** Quadrants 3 and 4 are still bought around day 11 because
   cash is tied up in melon seeds until the day-10 harvest. Reserving toward the
   next land price, or deferring melon, is probably worth several thousand.
3. **Endgame seed waste.** Traces show ~13 melon seeds ($1,040) and 40+ idle
   tiles still held on day 29. Stop buying seeds whose cycle cannot finish.
4. **Mid-day porter runs.** Only the day-29 `DROP` is implemented. Producing
   >100 units/day currently overflows the shed; ferrying to the shed mid-day
   would lift the hard ~100 units/day ceiling.
5. **Self-play validation.** Everything so far is measured against `random`,
   `pass`, and v12 — all of which barely touch the shared market. A real
   opponent competing for the same scarcity premiums will change crop
   valuations. Run `bench.py --agent main:agent --opp main.py --swap`.
