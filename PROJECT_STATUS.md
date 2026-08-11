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

The v12 agent scored **$4,464** vs `random`. Current agent is ~18x that.
Runtime is 4.6 ms/turn against a 1000 ms `actTimeout`, so there is a lot of
compute headroom left.

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
KAG_MAX_GEESE=8 uv run bench.py --opp pass -n 16 --workers 16   # ~$63k, i.e. worse
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
| `MAX_GEESE` | 0 | flock off; 4→−$10k, 8→−$17k, 16→−$25k |

---

## 5. What's still pending

**Not started**

1. **Cut the walking.** 51.7% of unit-actions are moves, another 11.5% are
   `PASS`. Assignment is greedy per-turn with no notion of a route, so units
   criss-cross the farm. Biggest remaining lever on the crop engine — and the
   precondition for the flock ever paying.
2. **Land timing.** Quadrants 3 and 4 still land around day 11 because cash is
   tied up in melon seeds until the day-10 harvest. Reserving toward the next
   land price is probably worth several thousand.
3. **Self-play validation.** Everything is measured against `random`, `pass`,
   and v12, none of which really compete for the shared market. Run
   `bench.py --agent main:agent --opp main.py --swap`.
4. **The panic-dump rule is mispriced.** When
   `shed_fill + incoming > SHED_CAP - 10`, `reserve_frac` drops to 0.05 and the
   agent sells anything at almost any price. Flock traces showed it dumping
   melon at **$4** against a $250 base. Overflow really is discarded so the rule
   is right in principle, but it should dump the *cheapest* items, not
   everything. This is a latent defect that can fire without geese whenever crop
   throughput is high — smaller job than #1 and a real bug rather than an
   enhancement.

**Built but parked**

5. **Goose engine** — complete behind `MAX_GEESE=0`. Only revisit after #1.

**Housekeeping**

6. `debug_wrapper.py` is redundant with `actions.py`/`trace.py`; drop it whenever.
7. **`main.py` has not been submitted to Kaggle yet.** The work is committed and
   pushed; the submission is the outstanding step.

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
