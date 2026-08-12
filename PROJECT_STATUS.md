# Kaggriculture — Status, Runbook, and Submission

Branch `KA-agent`. Every number here was measured with `bench.py` over fixed
seeds, not estimated.

> 📄 **A formatted version of this document is `PROJECT_STATUS.html`** — open it
> with `xdg-open PROJECT_STATUS.html`, or double-click it. Self-contained (all
> CSS inline, no external fonts or scripts), works offline, follows your system
> light/dark theme.
>
> **This `.md` is the source of truth.** If you change something here,
> regenerate the HTML rather than hand-editing it, or the two will drift.
>
> 📘 For **how the code actually works** — every `.py` file explained, the turn
> logic step by step — see **`CODE_GUIDE.pdf`** (13 pages, source
> `CODE_GUIDE.html`). This document is status; that one is understanding.
> Re-render it after editing the HTML with:
>
> ```bash
> google-chrome --headless --no-pdf-header-footer \
>   --print-to-pdf=CODE_GUIDE.pdf CODE_GUIDE.html
> ```

---

## 1. What to upload

**Upload `main.py` on its own. Not a zip.**

```
Kaggle → Submit to Competition → File Upload → Browse Files → main.py
```

Or from the terminal:

```bash
kaggle competitions submit -c kaggriculture -f main.py -m "porter runs; ~78k vs pass"
```

It is a single self-contained file importing only `math` and `os`, so there is
nothing to bundle. The zip/gz/7z option exists for agents split across several
files, which would then need `main.py` at the top level of the archive.

Verified against the exact path Kaggle uses:

- Kaggle runs `[v for v in env.values() if callable(v)][-1]` — the **last
  callable defined in the file**, whatever its name. That is `agent`. ✅
- Loaded as a file path rather than an imported module, it scores $77,114 over
  8 games, matching the module numbers. ✅

**Nothing else in the repo gets uploaded.** `bench.py`, `tune.py`, `trace.py`,
`actions.py`, `baselines/`, and the docs are local development tooling.

> ⚠️ Kaggle `exec`s the file just to grab `agent`, so **never define a function
> or class below `agent`** in `main.py` — it would silently become the submitted
> agent. A bare `if __name__ == "__main__":` block is safe (and dead on Kaggle);
> a `def main():` under it is not.

---

## 2. Where the agent stands

| Matchup | Games | Mean | Median | Min | Winrate |
|---|---|---|---|---|---|
| vs `random` | 16 | **$81,166** | $80,938 | $72,201 | 16/16 |
| vs `pass` (deterministic, used for tuning) | 48 | **$78,475** | $79,689 | $48,171 | 48/48 |
| vs old **v12** agent, both seats | 20 | **$74,635** | $73,885 | $55,793 | 20/20 |
| **self-play**, both seats | 16 | **$43,841** | $44,334 | $23,881 | see below |

The v12 agent scored **$4,464** vs `random`. Current agent is ~18x that.
Runtime is 4.6 ms/turn against a 1000 ms `actTimeout`, so there is a lot of
compute headroom left.

### `OPP_SUPPLY=1.0` — the contested-market fix (2026-08-11)

Those rows are all measured with `OPP_SUPPLY=0`. Against a frozen copy of that
agent, the shipped default of **1.0** now wins **99 of 128 games** with a mean
margin of **+$7,514**:

| Opponent | before | after | Δ |
|---|---|---|---|
| `pass` (n=32) | $77,248 | $77,366 | +$118 — flat |
| `v12` (n=16 swap) | $75,192 | $70,431 | **−$4,761** |
| the `0.0` agent (n=128) | tie | +$7,514 | **+$7,514** |

**This is a trade, not a strict improvement.** `1.0` assumes the opponent
supplies as much as we do; against a weak supplier like v12 that over-corrects
and costs $4.8k. It still wins 100% of those games — it just wins by less. The
trade is right on a leaderboard of live agents and would be wrong against a
field of passive ones.

### ⚠️ The self-play number is the one to quote

**$78,475 is a benchmark, not a forecast.** Against an opponent that genuinely
competes for the shared market, the score falls **44%**, to ~$44k. Every other
row in that table is against an opponent that barely sells anything, so our
agent alone drains the town's demand and collects every scarcity premium.

Do not report $78k as an expected leaderboard result.

The winrate column is meaningless for self-play: the agent is deterministic, so
against a copy of itself it plays a **mirror match** and finishes on identical
dollars. Roughly two-thirds of seeds are exact ties, and `bench.py` scores a tie
as a non-win, which is why it prints `3/16 = 19%`.

```
seed 1000:  seat0 $23,881   seat1 $23,881   TIE
seed 1003:  seat0 $48,745   seat1 $60,640   seat1
```

Reproduce with:

```bash
uv run bench.py --agent main:agent --opp main.py --swap -n 8 --workers 16
```

### How it works

`main.py` prices **every possible action in dollars**, then matches units to
jobs by value per action spent reaching them. Each turn:

1. **Scan** the farm into empties / weeds / plants, and total our unsold
   `pipeline` per item.
2. **Value crops** at the market inventory they will *face at harvest*, not
   today's — `today − town_drawdown_over_cycle + our_pipeline`.
3. **Rank crops** by profit against whichever resource is currently scarce:
   cash on day 0, land by mid-season.
4. **Build a job list** priced in dollars — HARVEST, WATER, DIG, PLANT, DROP.
5. **Assign** by ranking every (unit, job) pair on `value / (distance + 1)`.
6. **Market orders** in resolution order: SELL → BUY_LAND → HIRE → BUY_SEED.

---

## 3. What changed this session

### ✅ Mid-day porter runs — shipped, +$2,202

Units now walk produce to the shed **mid-day** once the day's haul is
outgrowing it, not only on day 29. Goods reach the shed only at end of day, and
anything past the 100-item cap is **discarded silently** — so ferrying early,
where the SELL orders can drain it, recovers output that was being thrown away.

Paired over 48 seeds vs `pass`:

| | Mean | Median | Min |
|---|---|---|---|
| Porter **on** | $78,475 | $79,689 | $48,171 |
| Porter **off** | $76,273 | $76,503 | $43,547 |
| **Delta** | **+$2,202** | **+$3,186** | **+$4,624** |

It lifts the floor harder than the mean, which is the expected signature: it
pays in exactly those games where production overran the shed.

> Measure this one at **n ≥ 48**. At n=16 the effect flipped sign between seed
> windows and briefly looked negative.

### ❌ Goose / egg engine — built, measured, switched off

Fully implemented (`BUILD_COOP`, `BUY_ANIMAL`, `PICKUP` at the shed, `PLACE`,
then daily `FEED`/`CARE`/`HARVEST`/`COLLECT_FERTILIZER`, plus a wheat feed
reserve and `BUY_PRODUCT` top-ups). It is behind `MAX_GEESE`, which now
**defaults to 0**, because it loses money at every size measured:

| `MAX_GEESE` | 0 | 4 | 8 | 16 |
|---|---|---|---|---|
| mean vs `pass` | **$79,472** | $69,309 | $62,858 | $54,027 |

The previous handoff called this "the largest single remaining lever" and
costed it per *tile* — but tiles are not the binding constraint, **unit-actions
are**. A bird grosses ~$150/day (2 eggs at ~$42, 1 fertilizer at ~$70, less a
$35 wheat) but needs ~7 actions/day to collect it, and `actions.py` shows
**51.7% of every unit-action is already just walking**. Traces showed it only
managing to feed 7–11 of 16 birds on a given day.

`GOOSE_UPKEEP` double-charging crew capacity was tested as the alternative
explanation and ruled out (−112, noise).

### 🔎 Self-play measured for the first time — the score halves

Run at the end of the session, before submitting. Against a copy of itself the
agent scores **$43,841** against **$78,475** vs `pass` — a **44% drop**.

Nothing is broken; the earlier numbers were simply measured against opponents
that do not compete. Both farms now dump the same crops into the same shared
inventory, so prices fall twice as fast, the scarcity premiums that drove much
of the strategy get competed away, and melon's one-shot ~$26k prize is split
rather than taken whole.

The immediate suspect was `crop_profit`, which had no term for opponent supply.
That is now fixed — see below.

### ✅ Phase 7: quadrant zoning — shipped, +$4.5k / 78% winrate (2026-08-12)

`actions.py` showed 48.3% MOVE + 19.4% PASS — two-thirds of the crew's day
producing nothing. Assignment was greedy per-turn on `value / (distance + 1)`
with no route-awareness, so units converged on whichever single job scored
highest and criss-crossed the farm.

**Tried first, and discarded:** exact-job hysteresis (`STICKY`) — a score
bonus for continuing toward the exact job a unit was walking to last turn,
both ungated and range-gated to "almost there" (last 2 steps). Replicated on
3 independent seed sets: a consistent loss, roughly −$7k to −$12k at
`STICKY=1.0`. Action-count profiling showed barely any change in MOVE/PASS
share, so the loss wasn't from more walking — pinning a unit to a decaying-
value target cost more in missed better options than it saved in switching.
Left in the code, defaulted to `STICKY=0.0` (verified exact no-op), in case a
smarter targeting rule is worth revisiting later.

**What worked:** quadrant zoning (`QUAD_BONUS`). Each unit gets a "home"
quadrant — a stateless function of its index and the unlocked-quadrant list,
so it needs no memory and survives the daily hand respawn cleanly (hands are
wiped and rehired every morning; a remembered-target scheme would go stale
across that boundary). Jobs in a unit's home quadrant get a score multiplier,
spreading the crew across the farm instead of letting them all chase the same
hot job.

Swept 0.1 → 5.0 against a frozen HEAD opponent, replicated on 3 independent
seed sets (n=24 to 128, `--swap`). Plateaus from ~2.0:

| Seed set | n | Mean | Opp mean | Winrate |
|---|---|---|---|---|
| seed0=4000 | 64 | $53,463 | $48,223 | 55/64 = 86% |
| seed0=1000 (final confirmation) | 128 | $55,575 | $51,044 | 100/128 = 78% |

Shipped as the new default, `QUAD_BONUS=2.0`, in the middle of the plateau
rather than at an edge. Action profile confirms the mechanism: PASS dropped
21.6% → 16.2%, and every productive action (WATER, PLANT, HARVEST, DIG) rose
— it converts idle turns into work rather than adding more walking.

No regression elsewhere: vs `pass` $77,366 → $79,896; vs `v12` $70,431 →
$70,914.

**Also checked and ruled out as a bug:** hired hands spawn at shed-access
tiles, three of which are `LOCKED` until their quadrant is bought. Read the
engine source (`kaggriculture.py`) — movement onto `LOCKED` tiles is
explicitly allowed and `DROP`/shed operations resolve before the `LOCKED`
guard, precisely so a hand spawned there isn't stranded. Nothing to fix.

### ✅ Phase 8: cow and sheep — shipped, +$8.4k / 68% winrate (2026-08-12)

Re-derived the goose-only flock decision deliberately deferred from an
earlier session, now that Phase 7 changed the action-cost structure it
depends on. The `main.py:80` comment ("only GOOSE is worth the tiles")
judged animals on lifetime market cap; on $-per-action, cow and sheep win —
they harvest every 2-3 days instead of daily for roughly 2x the goose's
$26/action.

Generalized the goose-specific machinery to all three species (`ANIMALS`
gained `COW`/`SHEEP` with engine-verified params; `goose_value` →
`animal_value(species, placed_day)`; PLACE/BUILD/PICKUP/BUY_ANIMAL jobs all
loop over species now, ranked best-value-first so cow/sheep naturally win
the shared crew-time/cash budget over goose without a hand-coded
preference). Confirmed the FEED/HARVEST/CARE job-generation loop and
`animal_output()` were already fully generic before this change — only the
species-selection and structure-building logic needed to grow. Along the
way, fixed a latent bug: the escape-penalty term in the generic per-animal
FEED loop called the goose-only `goose_value()` regardless of which species
was actually about to escape (harmless while only GOOSE existed; would have
mispriced cow/sheep escapes).

Swept `MAX_ANIMALS` 4 → 24 against a frozen Phase-7 opponent; replicated on
4 independent 64-game seed sets:

| Seed set | `MAX_ANIMALS` | Mean | Opp mean | Winrate |
|---|---|---|---|---|
| seed0=5000 | 8 | $65,967 | $60,948 | 39/64 = 61% |
| seed0=6000 | 6 | $68,065 | $60,530 | 48/64 = 75% |
| seed0=2000 | 6 | $66,932 | $55,666 | 56/64 = 88% |
| seed0=1000 (final, n=128) | 6 | $65,519 | $57,112 | 87/128 = 68% |

Falls off past 12, flat by 24. Shipped `MAX_ANIMALS=6`. No regression
elsewhere: vs `pass` $79,896 → $86,937; vs `v12` $70,914 → $81,851.

### ✅ `OPP_SUPPLY` — pricing the supply we cannot see

`crop_profit` priced a planting at `today − town_drawdown + our_pipeline`. The
`pipeline` term holds **only our own** crop, because the opponent's fields are
not in the observation. So every crop was overvalued in a contested game, worst
on exactly the crops we rank highest — a symmetric opponent wants those for the
same reasons we do.

The fix scales the pipeline term by `1 + OPP_SUPPLY` at both valuation sites
(`crop_profit`, `start_inventory`). `0.0` reproduces the old agent exactly —
verified to the dollar on mean, median, min, max and stdev.

Swept 0 → 3 against a frozen copy of the `0.0` agent, **two independent 64-game
seed sets**, `--swap` on both:

| OPP_SUPPLY | run 1 margin / WR | run 2 margin / WR | combined WR |
|---|---|---|---|
| 0.0 (control) | $0 / 20% | $0 / 17% | 24/128 = 19% |
| 0.25 | +$5,389 / 81% | −$439 / 56% | 88/128 = 69% |
| 0.5 | −$1,801 / 39% | +$1,144 / 59% | 63/128 = 49% |
| 0.75 | +$4,810 / 66% | +$7,085 / 75% | 90/128 = 70% |
| **1.0** | **+$6,115 / 73%** | **+$8,912 / 81%** | **99/128 = 77%** |
| 1.5 | +$4,318 / 77% | +$613 / 62% | 89/128 = 70% |
| 2.0 | +$527 / 44% | +$158 / 48% | 59/128 = 46% |
| 3.0 | −$21,044 / 0% | −$19,886 / 0% | 0/128 = 0% |

**Run the replication.** `0.25` led run 1 at 81% and went *negative* on fresh
seeds. Reading the winner off a single sweep would have shipped a no-op. `1.0`
is the only value that is best in both runs — and it is the a-priori correct
answer against a mirror, which is a good sign it is mechanism and not curve fit.

Past 2.0 it falls off a cliff: at `3.0` every crop prices as doomed, the agent
stops planting, and it loses 0/128 — with the *lowest* stdev in the table,
because it fails uniformly rather than wildly.

The control is exact: `0.0` gave identical means for both seats in both runs
($44,421/$44,421 and $46,165/$46,165), confirming no seat bias and no env-var
leaking into the frozen opponent.

Reproduce:
```bash
for X in 0.0 0.25 0.5 0.75 1.0 1.5 2.0 3.0; do
  KAG_OPP_SUPPLY=$X uv run bench.py --agent main:agent \
      --opp <frozen-copy-of-0.0-agent>.py --swap -n 32 --seed0 1000
done
```

### 🔎 Engine facts established (verified against the source)

- `BUILD_COOP` is **free** — the $300 is the bird. Requires a `None` tile.
- Animals produce **whether or not they are fed**. Feeding governs survival
  (two consecutive dry nights and the bird escapes, structure intact) and lets
  a fed night spend the `CARE` bonus.
- `FEED` draws wheat from the **unit's own inventory**, not the shed, so every
  feed cycle needs a `PICKUP` run first. This is what makes it action-hungry.
- `max_held` caps only *uncollected* product, so lifetime output is unbounded.
- **FERTILIZER is in no shop's list and is excluded from
  `TOWN_CENTER_PRODUCTS`** — its inventory only moves when we sell, making it a
  one-shot ~$25k prize (price floors after ~495 units), exactly like melon.
- `BUY_ANIMAL` lands the bird in the **shed**, against the 100-item cap.

---

## 4. How to run it

All commands from the repo root. Timings measured on a 16-core machine.

| Command | What it does | Time |
|---|---|---|
| `uv run bench.py --opp pass -n 16 --workers 16` | Score over 16 games | 9 s |
| `uv run bench.py --opp pass -n 48 --workers 16` | Score over 48 games | 29 s |
| `uv run bench.py --opp random -n 16 --workers 16` | vs the built-in random agent | 9 s |
| `uv run bench.py --opp baselines/v12.py -n 10 --swap` | Regression vs old agent, both seats | 12 s |
| `uv run bench.py --agent main:agent --opp main.py --swap -n 8` | **Self-play** — the only contested-market number | 17 s |
| `uv run trace.py --seed 2003 --opp pass` | One game, day by day | 5 s |
| `uv run actions.py --seed 2003 --opp pass` | Where the crew's day goes, by op | 5 s |
| `uv run tune.py MAX_UNITS 10 12 14` | Sweep one parameter, paired | 40 s |

A single game costs ~4.6 s of CPU; with 16 workers you get ~1.7 games/second.
Everything above finishes in under a minute — run them interactively, don't
bother backgrounding them.

### `uv run python main.py` prints nothing — that is correct

`main.py` is the agent **module**, not a program. It defines constants and
functions and exits; nothing calls `agent()` unless a harness does. Silence and
exit code 0 mean the file is healthy. Use `trace.py` to actually watch it play.

### Two things that will save you time

- **`KAG_DEBUG=1` disables the `try/except` in `agent`**, so exceptions surface
  instead of silently degrading to `PASS`. Always develop with it — without it,
  a crashing agent just looks like a bad score.
  ```bash
  KAG_DEBUG=1 uv run bench.py --opp pass -n 4 --workers 4
  ```
- **Tune against `pass`, never `random`.** The built-in `random_agent` calls
  `random.Random()` with no seed, adding ~3.5% run-to-run noise that drowns
  real effects.

### Every tunable is an env var

Prefix any constant in `main.py` with `KAG_`:

```bash
KAG_MAX_ANIMALS=8 uv run bench.py --opp pass -n 16 --workers 16
KAG_PORTER_FILL=10.0 uv run bench.py --opp pass -n 48           # porter runs off
```

| Param | Value | Notes |
|---|---|---|
| `MAX_UNITS` | 12 | 8→$66k, 10→$69k, **12→$69k**, 14→$63k |
| `TILES_PER_UNIT` | 6.0 | 5→$48k (over-hires), 6→$71k, 8→$66k |
| `MOVE_COST` | 7.0 | flat 3–7; 10→$48k, 15→$46k |
| `SEED_RATION` | 6 | 4→$62k, **6→$77k**, 10→$74k, 20→$68k |
| `LAND_BUFFER` | 800 | 200→$50k (starves seeds); ≥400 all equal |
| `PORTER_FILL` | 0.6 | shed fill that starts mid-day drops; +$2,202 vs off |
| `QUAD_BONUS` | 2.0 | Phase 7; plateaus 2.0-5.0, 81-86% winrate vs frozen HEAD |
| `MAX_ANIMALS` | 6 | Phase 8, goose+cow+sheep; 4→+$9k, **6-8→+$5-11k**, 24→flat. Pre-Phase-7 goose-only: 4→−$10k, 8→−$17k, 16→−$25k |

---

## 5. What's still pending

**Not started**

1. **Land timing.** Quadrants 3 and 4 still land around day 11 because cash is
   tied up in melon seeds until the day-10 harvest. Reserving toward the next
   land price is probably worth several thousand.
2. **The panic-dump rule is mispriced.** When
   `shed_fill + incoming > SHED_CAP - 10`, `reserve_frac` drops to 0.05 and the
   agent sells anything at almost any price. Flock traces showed it dumping
   melon at **$4** against a $250 base. Overflow really is discarded so the rule
   is right in principle, but it should dump the *cheapest* items, not
   everything. This is a latent defect that can fire without geese whenever crop
   throughput is high — a real bug rather than an enhancement.

**Housekeeping**

3. `debug_wrapper.py` is redundant with `actions.py`/`trace.py`; drop it whenever.

Superseded/stale: an earlier version of this item tracked submission-lag
between the working build and the leaderboard. As of the Phase 8 commit,
`main.py` has been submitted current with HEAD (submission `55453124`,
2026-08-12). See §2 for current bench numbers; leaderboard score needs a
day+ to converge before it's worth quoting (skill rating, not dollars — see
`NEXT_SESSION.md` trap list).

---

## 6. Files

| File | Purpose | Upload? |
|---|---|---|
| `main.py` | **The agent.** Self-contained, stdlib only. | ✅ |
| `bench.py` | Parallel seeded benchmark | — |
| `tune.py` | One-parameter sweeps | — |
| `trace.py` | Day-by-day trace of one game | — |
| `actions.py` | Action-budget profiler | — |
| `baselines/v12.py` | Frozen old agent, for regression checks | — |
| `kaggriculture_handoff.md` | Deep technical handoff (engine facts, design) | — |
| `PROJECT_STATUS.md` | This document — **source of truth** | — |
| `PROJECT_STATUS.html` | Formatted, self-contained rendering of this document | — |
| `CODE_GUIDE.pdf` | **Code walkthrough** — every `.py` file explained, 13 pages | — |
| `CODE_GUIDE.html` | Source for the PDF; re-render with headless Chrome | — |
| `debug_wrapper.py` | Old ad-hoc debug script, redundant | — |
