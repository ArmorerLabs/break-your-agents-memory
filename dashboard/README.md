# Projector dashboard

Renders real run folders - no mock data. `build_data.py` reads a run
(`run.json`, `summary.json`, the trial's `log.jsonl`, `egress.log`,
provenance) and writes `data.js`; the render scripts draw exactly that.

## Build

```bash
python dashboard/build_data.py runs/golden-chain --setting none --trial 1
```

Arguments: the run folder (positional), `--setting` (whose trial to draw in
the live view, default `none`), `--trial` (default 1).

The committed `data.js` was built from `runs/golden-chain` (fixtures mode);
rebuild it from any run you care about.

## View

```bash
python -m http.server -d dashboard 8000
# open http://localhost:8000?view=live   (also ?view=score, ?view=board)
```

- **Live run** - the node-link graph (assistants, edges labeled with the
  real shared files, signal squares MEM/SHARED/UPLD) and the session
  transcript from `log.jsonl` (tool calls, results, defense blocks and
  wraps, benign results).
- **Scoreboard** - the real hop-rate table with the pass lines drawn
  (half of baseline hop-2; 90% of baseline benign), verdicts including
  INCONCLUSIVE.
- **Leaderboard** - every scored defense (custom ones included) ranked by
  the pass rule, plus the cut-vs-kept scatter.

The top-right note always shows the run's evidence label
(`scripted-scenarios` / `recorded-replay` / `live-measured`) - the dashboard
never claims more than its data.

## Screenshots (dev convenience, projector prep)

```bash
node dashboard/shoot.mjs   # writes shots/live.png, score.png, board.png
```

Needs a local Chrome and a `puppeteer-core` install reachable via
`PUPPETEER_REQUIRE_PATH` (defaults to a dev-machine path); override
`CHROME_PATH` for nonstandard Chrome locations. This is a convenience for
producing projector stills, not part of the lab.
