# Kaggriculture — start-here brief for the next session

**Written:** 2026-08-12 · **Branch:** `KA-agent` · **HEAD:** (post-top-10-replay-sweep commit, see `git log`)

Open this in a fresh chat and say *"read NEXT_SESSION.md and start Phase 10."*
Everything needed to resume is here or linked from here.

---

## 0. The one question first: should I submit `main.py`?

**Yes.**

Today's session (after Phase 8 shipped cow/sheep) did two rounds of
leaderboard-replay analysis:

1. Found `land_reserve` was starving the flock of cash for most of the
   game → shipped `MAX_LAND_BUYS=1`, `MAX_ANIMALS=10` (was 6): **98%
   winrate, +$13.3k** vs the prior build.
2. Found every top-10 replay checked runs **zero geese** → shipped
   `GOOSE_ENABLED=0`: **77% winrate, +$4.5k** vs that build.

Compounded, both are in the current `main.py` and already submitted
(submission ref noted in git log / Kaggle history around 2026-08-12).

Pre-flight checks:

| Check | Result |
|---|---|
| `agent` is the last callable in the file | ✅ |
| Signature is `agent(obs)` | ✅ |
| Runs clean vs `pass` | ✅ $93,042 mean, 32/32 |
| Stdlib only, self-contained | ✅ |
| `KAG_DEBUG=1` runs (both changes) — no hidden exceptions | ✅ |

---

## 1. State of the repo

Working tree: current changes are in `main.py`, `PROJECT_STATUS.md`,
`.gitignore` (added `replays/`, which holds downloaded episode replays used
for leaderboard analysis — not source, don't commit them). Check
`git status` and `git log origin/KA-agent..HEAD` before assuming what's pushed.

### Measured performance (current HEAD: `QUAD_BONUS=2.0`, `MAX_LAND_BUYS=1`, `MAX_ANIMALS=10`, `GOOSE_ENABLED=0`)

| Matchup | Games | Ours | Opponent |
|---|---|---|---|
| vs `pass` | 64 | $93,042 | $3,000 |
| vs `baselines/v12.py` | 64 (swap) | $87,995 | $3,606 |
| vs prior build (frozen, pre-`GOOSE_ENABLED`) | 128 (swap) | $73,072 | $68,596 |

**Quote the frozen-HEAD number, not the `pass` number** — same logic as
every prior session: `pass` doesn't compete for the market.

---

## 2. What this session did

### ✅ `MAX_LAND_BUYS=1` — land reserve was starving the flock (+$13.3k, 98% winrate)

`land_reserve` held the *entire* next quadrant's price + buffer,
continuously, until bought — across all 3 purchasable quadrants in
sequence. With `LAND_MIN_DAYS=[5,6,8]` that reserve is active almost the
whole game, choking `spare_cash` and delaying real animal investment until
day 21+. A downloaded top-of-leaderboard replay (episode `92267113`)
prompted the investigation by showing an almost-all-animal winning economy
(12-13 animals, 0-1 crop tiles) — but copying its exact numbers
(`MAX_LAND_BUYS=2`, matching their stop-at-3-quadrants pattern) was worse
than going further: `MAX_LAND_BUYS=1` (only buy NE, skip SW/SE) won, with
`MAX_ANIMALS`'s true optimum moving from 6 to 10 once land stopped
competing for cash. Full writeup: `PROJECT_STATUS.md`, "Leaderboard-replay
analysis" section.

### ✅ `GOOSE_ENABLED=0` — every top-10 player runs zero geese (+$4.5k, 77% winrate)

Pulled the real leaderboard (`kaggle competitions leaderboard`) and
downloaded 5 more episodes from the then-#1 player (カワシギ), whose
opponents are themselves other top-10 players. Universal pattern: 3
quadrants, cow+sheep only, **zero goose**, and カワシギ's own flock was an
exact, repeated 10 COW + 4 SHEEP = 14 animals across 4 separate games.

Copying their land/animal *counts* directly (`MAX_LAND_BUYS=2/3`,
`MAX_ANIMALS=12-14`) didn't transfer — lost or exact-tied against our
shipped build every time (the tie is diagnostic: it means our agent's
achieved flock never even reaches the cap under those land settings, so
the cap value doesn't matter). But their *behavioral* difference — zero
geese, ever — did transfer: goose only wins our value-ranking early
because it matures fastest (`first_yield_day=4` vs cow's 8, sheep's 6),
grabbing budget a cow/sheep would have used better once mature. Excluding
it from the species pool replicated cleanly on 2 independent seed sets.
Full writeup: `PROJECT_STATUS.md`, "Top-10 replay sweep" section.

**The throughline for both:** a leaderboard replay is a hypothesis
generator, not a target to copy. What actually transferred was a
qualitative behavior (zero goose), not a quantitative target (land count,
animal count) — those need to be independently verified against *this*
agent's own cash/action mechanics, which differ enough from whatever the
top players are running that their raw numbers don't carry over. See trap
#12 below before trying this again with a new replay.

### How to pull and read a replay, if you do this again

```bash
# Get the current leaderboard
.venv/bin/kaggle competitions leaderboard kaggriculture -s

# Get a submission ID from a leaderboard game-history URL you're looking at
# (kaggle.com/.../leaderboard?submissionId=XXXXX&episodeId=YYYYY), then:
.venv/bin/kaggle competitions episodes <submission_id> --format json

# Download a specific completed episode
.venv/bin/kaggle competitions replay <episode_id> -p replays
```

The downloaded JSON is the same shape `bench.py`/`trace.py` already
consume: `data['steps'][turn][player_idx]['observation']['farms'][player_idx]`
gives full farm state (tiles, money, animals, quadrants) at any point.
`data['info']['TeamNames']` gives the two player names/order. Index by
`hour == 23` to sample end-of-day snapshots without walking all 720 steps.

**Important:** `print()` inside an agent function called via
`kaggle_environments`'s `env.run()` is silently swallowed — accumulate
into a list and print after `env.run()` returns, not during.

---

## 3. Remaining work, in the order I'd do it

### ❌ Phase 9 — Panic-dump rule — investigated 2026-08-13, no fix shipped

The observation was real (melon dumped at $4 against a $250 base when
`reserve_frac` collapses to `0.05` under shed pressure), but "protect the
expensive items, dump the cheap ones instead" benchmarked as a **net
loss** (17%/11% winrate under an artificially small `SHED_CAP` built to
force panic to fire often). Traced why: the protected expensive item then
almost never clears under its *normal* reserve either, so it just becomes
dead stock that permanently eats shed capacity — worse than the
"wasteful" blanket fire-sale, which at least liquidates everything
reliably. Full writeup in `PROJECT_STATUS.md` under "Phase 9". Don't
re-attempt this exact fix without a new idea — see trap #13.

### 🔜 Phase 10 — Land timing: `LAND_MIN_DAYS`/`LAND_BUFFER`, not yet re-swept  ← **START HERE**

`MAX_LAND_BUYS=1` (§2) answered *how many* quadrants to buy. The *when* —
`LAND_MIN_DAYS=[5,6,8]` gating when the reserve activates, and whether
`LAND_BUFFER=800` is still the right liquidity cushion now that
`GOOSE_ENABLED=0` changes early-game cash flow too — hasn't been re-swept
since either change. Likely smaller than the `MAX_LAND_BUYS` win, but
cheap to check.

### Housekeeping

- `debug_wrapper.py` is redundant with `actions.py` / `trace.py`. Delete
  whenever.
- `PROJECT_STATUS.html` and `CODE_GUIDE.pdf`/`.html` are stale (last
  re-rendered before Phase 7). Re-render if anyone's going to read the
  formatted versions:
  ```bash
  google-chrome --headless --no-pdf-header-footer \
    --print-to-pdf=CODE_GUIDE.pdf CODE_GUIDE.html
  ```
- `replays/*.json` (gitignored) are ~30MB each; delete them from disk
  whenever if space matters, they're not needed once their analysis is
  written up in `PROJECT_STATUS.md`.

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
TUNE_OPP=/tmp/prev.py .venv/bin/python tune.py MAX_ANIMALS 8 10 12

# Where the time goes
.venv/bin/python actions.py

# Day-by-day trace of one game (own agent)
.venv/bin/python trace.py

# Leaderboard + replay analysis (see §2 above for the full pattern)
.venv/bin/kaggle competitions leaderboard kaggriculture -s
.venv/bin/kaggle competitions episodes <submission_id> --format json
.venv/bin/kaggle competitions replay <episode_id> -p replays
```

**Every constant is an env var.** `_tune("NAME", default)` reads `KAG_NAME`.
Sweep without editing the file. `KAG_DEBUG=1` disables the try/except so
exceptions actually surface instead of silently returning no-ops.

Engine source of truth — read it rather than guessing at semantics:
```
.venv/lib/python3.13/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py
```

Submitting (kaggle CLI is installed in the project venv — `.venv/bin/kaggle`,
credentials at `~/.kaggle/access_token`):
```bash
.venv/bin/kaggle competitions submit kaggriculture -f main.py -m "message"
.venv/bin/kaggle competitions submissions kaggriculture
```

---

## 5. Traps this project has already fallen into

Read these before running an experiment. Each one cost real time.

1. **Replicate before you believe a sweep.** `OPP_SUPPLY=0.25` led sweep 1 at
   **81%** and went **negative** on fresh seeds. Always re-run the *whole
   curve* on an independent seed set, not just the winners.

2. **A deterministic agent vs a copy of itself ties exactly.** Mirror matches
   show ~6–20% "winrate" — that is the **neutral** result, not a loss. Don't
   panic at it, and don't cite it as evidence of anything. An *exact* mean
   tie between two *different* configs, though, is a different signal — see
   trap #12.

3. **`pass` is not an opponent.** It flatters everything, because nothing
   competes for the market. Tune and verify against a frozen real build.

4. **Value harvests at marginal revenue, not sticker price.** The first
   fertilizer cut lost **$22k** by pricing extra units at `price_of(crop)`.
   Going through `batch_revenue(crop, start_inventory(crop, 3), n)` recovered
   $13.5k of it. Prices move as you sell — always price the batch.

5. **Buy per *carrier*, not per opportunity.** Fertilizer bought one sack per
   profitable tile; capping at `1 + len(hands)` was worth $2.6k.

6. **Guess less, profile more.** A guess that fertilizer's loss was action
   cost was wrong (`actions.py` showed it was 2.5% of unit-actions). This
   session's `MAX_LAND_BUYS` fix came from *tracing* cash/animal count day by
   day, not from guessing the flock cap was the bottleneck (it wasn't).

7. **Nothing callable may be defined below `agent`** in `main.py`. Kaggle's
   loader runs the *last* callable in the file.

8. **`OPP_SUPPLY=1.0` is a trade, not a free win.** It costs $4.8k against the
   weak-supplier `v12` baseline. Still the right call — 99/128 vs a real
   competitor — but don't describe it as a strict improvement.

9. **Persistent state must survive daily resets, not just episode resets.**
   Hands are wiped and rehired every morning, so a unit index doesn't mean
   the same physical unit two days running. Prefer stateless designs
   (`QUAD_BONUS`) over stateful ones (`STICKY`) when the data is cheap to
   recompute every turn.

10. **When generalizing single-case code to multiple cases, check each
    piece is actually still single-case before assuming it needs work.**
    Phase 8 found the per-animal `FEED`/`HARVEST`/`CARE` job loop was
    *already* generic. Don't refactor code that's already correct.

11. **A shared resource pool needs a single accounting pass, not repeated
    independent checks.** `PASTURE` is shared between COW and SHEEP; the
    flock-sizing pass decrements a shared `pool` dict as each species
    claims free structures. The `BUY_ANIMAL` order block deliberately
    tolerates a small amount of double-booking (documented in its comment)
    — don't "fix" that without checking whether it's intentional.

12. **External play is a hypothesis generator, not a target to copy.**
    Two separate leaderboard-replay investigations this session found the
    same shape: the top players' raw *numbers* (land quadrants bought,
    flock size) did not transfer directly — copying them lost or exact-tied
    against what we'd already tuned. What transferred was a *qualitative*
    behavior (zero goose). When a replay's `MAX_ANIMALS`-equivalent
    produces an **exact mean tie** against a different cap value in your
    own bench, that's the tell that the cap isn't your real bottleneck —
    something else (usually cash) is capping the achieved value below both
    settings. Go find that something, don't just try more values of the
    cap.

13. **A benchmark under stress conditions beats a plausible mechanism.**
    Phase 9's "dump cheap, protect expensive" fix for the panic-sell rule
    sounded right from a single trace, but a paired benchmark (even one
    rigged with a tiny `SHED_CAP` to force the rare condition to fire
    often) showed it losing. The failure mode wasn't visible from the
    trace that motivated the fix — it only showed up by comparing full
    games. When a bug is real but rare, build a stress test before
    shipping the fix, not just before diagnosing the bug.

---

## 6. Where the deeper docs are

| File | What's in it |
|---|---|
| `PROJECT_STATUS.md` | **Source of truth.** Full experiment log, every result. |
| `PROJECT_STATUS.html` | Same, formatted and self-contained — **stale, re-render if needed.** |
| `kaggriculture_handoff.md` | Deep technical handoff — engine facts, design rationale. |
| `CODE_GUIDE.pdf` / `.html` | Every `.py` file explained, 13 pages — **stale.** |
| `README.md` | The full rulebook — crop/animal tables, price functions, buildings. |
| `AGENTS.md` | Kaggle submission and replay mechanics. |

---

## 7. Suggested opening message for the new chat

> Read `NEXT_SESSION.md`. Start Phase 10 — re-sweep `LAND_MIN_DAYS` and
> `LAND_BUFFER` now that `MAX_LAND_BUYS=1` and `GOOSE_ENABLED=0` have
> changed the cash dynamics they depend on. Measure with a paired swap
> benchmark against the current HEAD before keeping any change.
