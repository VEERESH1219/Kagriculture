# Kaggriculture — start-here brief for the next session

**Written:** 2026-08-12 · **Branch:** `KA-agent` · **HEAD:** `f4ccbb5`

Open this in a fresh chat and say *"read NEXT_SESSION.md and start Phase 7."*
Everything needed to resume is here or linked from here.

---

## 0. The one question first: should I submit `main.py`?

**It is safe to submit, but there is no point — it would be a duplicate.**

The build currently on the leaderboard (`OPP_SUPPLY=1.0`, seen at **506.1**) is
*behaviourally identical* to `main.py` at HEAD. Phase 5 added the fertilizer
engine but shipped it behind `FERT_ON=0`, and that was verified as an exact
no-op, not assumed:

```
main.py  vs  6f4f1b6:main.py   (16 games, --swap, seed0 9000)
  mean $50,455   opp $50,455      <- identical to the dollar
```

Pre-flight checks that also passed:

| Check | Result |
|---|---|
| `agent` is the last callable in the file | ✅ line 991, nothing callable below it |
| Signature is `agent(obs)` | ✅ |
| Runs clean vs `pass` | ✅ 8/8, mean $68,832 |
| Stdlib only, self-contained | ✅ |

**Recommendation: don't resubmit yet.** Submissions are the scarce resource —
spend the next one on a build that actually plays differently. Resubmit after
Phase 7 lands a measured gain.

**Also note:** the leaderboard number is a *skill rating, not dollars.* It
drifts ±7–8 points an episode and new submissions enter near a default and
converge slowly. 506.1 at 13 minutes old was still at entry rating and means
nothing. Observed band across the board: 509–716. Never read a single
observation as a result.

---

## 1. State of the repo

Working tree clean. One commit was unpushed as of writing (`f4ccbb5`) — check
`git log origin/KA-agent..HEAD` before assuming.

```
f4ccbb5  Phase 5: build the fertilizer engine, measure it, leave it off
6f4f1b6  Price the opponent's supply: OPP_SUPPLY, defaulted to 1.0
84e47de  Record the self-play result: the score halves against a real opponent
```

### Measured performance (current HEAD)

| Matchup | Games | Ours | Opponent |
|---|---|---|---|
| vs `pass` | 32 | $77,366 | $3,000 |
| vs `baselines/v12.py` | 32 (swap) | $70,431 | $2,804 |
| vs pre-`OPP_SUPPLY` build | 128 | $49,813 / $54,280 | $43,698 / $45,368 |

**Quote the self-play number, not the `pass` number.** Against a real
competitor for the same market the score roughly halves. `$77k` is a solo-market
fantasy; `~$50k` is the honest figure.

---

## 2. Remaining work, in the order I'd do it

### 🔜 Phase 7 — Cut the walking  ← **START HERE**

**Why first:** `actions.py` says **51.7% of unit-actions are moves** and another
**11.5% are `PASS`**. Nearly two-thirds of the crew's day produces nothing.
Assignment is greedy per-turn with no notion of a route, so units criss-cross
the farm.

This is both the biggest remaining lever on the crop engine *and* the
precondition for every parked feature — the goose and the fertilizer engine both
failed on **action cost**, so anything that makes actions cheaper reopens them.

Where to look in `main.py`:
- The scoring is `value / (distance + 1)` in the job-assignment loop. That
  denominator is the only route-awareness in the system.
- Jobs are re-ranked from scratch every turn, so a unit can be pulled off a
  half-finished walk by a job that got marginally better elsewhere. **Assignment
  hysteresis** (a stickiness bonus for continuing toward your current target) is
  the cheapest thing to try and probably the highest-value.
- Second idea: cluster jobs by quadrant and soft-assign units to zones, so the
  crew stops trading places.
- Third: the `PASS` share suggests units idle when no job clears the bar —
  consider a cheap "walk toward tomorrow's work" fallback.

**Also fold in the locked-spawn bug:** hired hands spawn at `(5,4)`, which is
**locked until the NE quadrant is bought**. Verify what the engine actually does
with a unit on a locked tile before designing around it — this may be costing
early-game hand-turns.

Add tunables as `_tune("NAME", default)` so they can be swept without edits.

### Phase 8 — Re-derive cow and sheep (analysis is already done)

The analysis ran last session. **The comment at `main.py:80` — *"Only GOOSE is
worth the tiles"* — is judging on the wrong metric.**

| | cost | productions | units | market cap | saturates at | solo net |
|---|---|---|---|---|---|---|
| Goose | $300 | 25 | 50 | uncapped | 400× | $1,944 |
| Cow | $400 | 11 | 22 | $6,181 | **3.5 animals** | $2,636 |
| Sheep | $500 | 8 | 16 | $7,928 | **3.7 animals** | $2,628 |

On lifetime market cap the comment is right: milk and wool saturate, egg never
does. But the goose didn't fail because egg saturated — **it failed on action
cost.** On that metric the ranking inverts:

| | feeds + cares + harvests | net | **$ per action** |
|---|---|---|---|
| Goose | ~25 + 25 + 25 = 75 | $1,944 | **$26** |
| Cow | ~21 + 21 + 11 = 53 | $2,636 | **$50** |
| Sheep | ~23 + 23 + 8 = 54 | $2,628 | **$49** |

Cow and sheep produce on 2- and 3-day intervals instead of daily — **half the
harvest actions for more money, roughly 2× the goose's action-efficiency.**
Ceiling is ~$10.5k combined across ~8 tiles.

**Do this after Phase 7**, because Phase 7 changes the cost structure that
decides the answer. Measuring animals now risks a false negative and parking
them wrongly — which is exactly the mistake the `main.py:80` comment already
made once.

Build cost is real: `ANIMALS` only knows `GOOSE`. Needs a `PASTURE` structure,
`BUILD_PASTURE`, and generalising the goose-specific valuation
(`goose_value`, `new_goose_value`, `free_coops`, `shed_geese`) — roughly a
150-line refactor.

### Phase 9 — Fix the panic-dump rule *(this is a live bug, not an enhancement)*

When `shed_fill + incoming > SHED_CAP - 10`, `reserve_frac` drops to `0.05` and
the agent sells **anything at almost any price**. Traces showed melon dumped at
**$4** against a $250 base.

Overflow really is discarded, so the rule is right in principle — but it should
dump the **cheapest** items, not everything. This can fire *without* geese
whenever crop throughput is high, so it is probably costing money right now.
Small, self-contained, worth doing even if the phases slip.

### Phase 10 — Land timing

Quadrants 3 and 4 land around **day 11** because cash is tied up in melon seeds
until the day-10 harvest. Reserving toward the next land price is probably worth
several thousand.

### Housekeeping

- `debug_wrapper.py` is redundant with `actions.py` / `trace.py`. Delete whenever.

---

## 3. How to run things

```bash
# Paired seeded benchmark. --swap cancels seat advantage. Ties are NOT wins.
.venv/bin/python bench.py --agent main.py --opp pass -n 32 --swap --seed0 1000
.venv/bin/python bench.py --agent main.py --opp baselines/v12.py -n 32 --swap

# Regression vs a frozen previous commit
git show 6f4f1b6:main.py > /tmp/prev.py
.venv/bin/python bench.py --agent main.py --opp /tmp/prev.py -n 64 --swap

# Sweep one parameter
.venv/bin/python tune.py --param KAG_MOVE_COST --values 3,5,7,9,11 -n 32

# Where the time goes
.venv/bin/python actions.py

# Day-by-day trace of one game
.venv/bin/python trace.py
```

**Every constant is an env var.** `_tune("MOVE_COST", 7.0)` reads
`KAG_MOVE_COST`. Sweep without editing the file. `KAG_DEBUG=1` disables the
try/except so exceptions actually surface instead of silently returning no-ops.

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

## 4. Traps this project has already fallen into

Read these before running an experiment. Each one cost real time.

1. **Replicate before you believe a sweep.** `OPP_SUPPLY=0.25` led sweep 1 at
   **81%** and went **negative** on fresh seeds. Always re-run the *whole curve*
   on an independent seed set, not just the winners.

2. **A deterministic agent vs a copy of itself ties exactly.** Mirror matches
   show ~6–20% "winrate" — that is the **neutral** result, not a loss. Don't
   panic at it, and don't cite it as evidence of anything.

3. **`pass` is not an opponent.** It flatters everything, because nothing
   competes for the market. The self-play number is the real one.

4. **Value harvests at marginal revenue, not sticker price.** The first
   fertilizer cut lost **$22k** by pricing extra units at `price_of(crop)`.
   Going through `batch_revenue(crop, start_inventory(crop, 3), n)` recovered
   $13.5k of it. Prices move as you sell — always price the batch.

5. **Buy per *carrier*, not per opportunity.** Fertilizer bought one sack per
   profitable tile; capping at `1 + len(hands)` was worth $2.6k.

6. **Guess less, profile more.** I attributed the fertilizer loss to action cost;
   `actions.py` showed FERTILIZE+PICKUP was 2.5% of unit-actions and mostly
   displacing `PASS`. The guess was wrong and cost a debugging cycle.

7. **Nothing callable may be defined below `agent`** in `main.py`. Kaggle's
   loader runs the *last* callable in the file.

8. **`OPP_SUPPLY=1.0` is a trade, not a free win.** It costs $4.8k against the
   weak-supplier `v12` baseline because assuming a symmetric opponent
   over-corrects. It was still the right call — it wins 99/128 against a real
   competitor — but don't describe it as a strict improvement.

---

## 5. Where the deeper docs are

| File | What's in it |
|---|---|
| `PROJECT_STATUS.md` | **Source of truth.** Full experiment log, every result. |
| `PROJECT_STATUS.html` | Same, formatted and self-contained. |
| `kaggriculture_handoff.md` | Deep technical handoff — engine facts, design rationale. |
| `CODE_GUIDE.pdf` / `.html` | Every `.py` file explained, 13 pages. |
| `README.md` | The full rulebook — crop/animal tables, price functions, buildings. |
| `AGENTS.md` | Kaggle submission and replay mechanics. |

---

## 6. Suggested opening message for the new chat

> Read `NEXT_SESSION.md`. Start Phase 7 — cut the walking. Profile first with
> `actions.py`, try assignment hysteresis as the first lever, and measure every
> change with a paired swap benchmark against the current HEAD before we keep it.
