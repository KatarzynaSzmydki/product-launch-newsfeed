---
name: daily-run
description: Run the daily product-launch pipeline end to end — fetch news, write a brief for each newly-confirmed launch, and commit. Use when asked to do the daily run, refresh the newsfeed, or generate pending briefs.
---

# Daily run

You are the generation step. `run_daily.py` does all the mechanical work and calls no LLM; you supply the one thing it can't — the launch-summary prose — and `publish_brief.py` gates and files it.

Keep this cheap. Do not `Read` the staging JSON files, do not `Read` or `Edit` `data/state.json` (it's ~60KB and grows daily — `publish_brief` maintains it in-process), and do not read `app.py` or the briefs you've already written.

## 1. Run the pipeline

```
python -m src.run_daily
```

It ends with a `=== PENDING GENERATION (n) ===` digest listing, for each launch awaiting a brief: the staging file path, the ticker and company, the matched keyword, and each source's headline. **That digest is everything you need.** If it says `Nothing to generate`, skip to step 4 (state.json may still have changed).

If you need the digest again later without re-running the pipeline: `python -m src.run_daily --show-pending`.

## 2. Write a summary for each pending launch

Two to four sentences of plain-language prose, paraphrased from the headlines. Hard rules — `publish_brief` rejects violations, so getting these right first time saves a retry:

- **No forecasting.** No price targets, nothing "expected to rise/fall", nothing "likely to" move.
- **No causal claims** linking the launch to the stock price.
- **No verbatim copying.** 15 consecutive words shared with a source headline is an automatic reject. Paraphrase.
- **Don't mention the stock figures.** The price/52-week table is rendered separately by `brief_template.py`; the summary is about the launch only.

Say only what the headlines support. If they're thin, write a short, hedged summary — don't invent product detail.

Sometimes the headlines are junk: the corroboration rule keys on `(ticker, keyword)`, so a price-forecast piece or an unrelated story that merely contains the verb can confirm a group. If the sources plainly aren't a product launch, **skip that entry** — leave its staging file alone and say so at the end. Publishing a bogus brief to a public repo is worse than publishing nothing.

## 3. Publish each one

One call per launch:

```
python -m src.publish_brief data/pending_generation/<id>.json --summary "<your prose>"
```

That single command renders the brief, validates it, writes it to `data/briefs/<date>_<TICKER>_<keyword>.md`, records `brief_path` + `generated_at` in `data/state.json`, and deletes the staging file. Don't pass an output path — it derives one.

- Exit 0 → `PUBLISHED <path>`. Done, move on.
- Non-zero → `FAIL: <reason>` and **nothing was written**; the staging file survives for a later run. Fix the prose against the stated reason and retry once. If it fails twice, leave it and move on — it'll be picked up next run.

(If the prose is long enough that shell quoting gets awkward, write it to a file and use `--summary-file <path>` instead.)

## 4. Commit — once, at the end

Only after every brief is published. A single commit, never one per brief, and never before generation finishes:

```
git add data/state.json data/briefs
git commit -m "Daily run: <n> briefs"
git push
```

`data/pending_generation/` is git-ignored and must never be committed — it's the only place raw scraped article text lives, and this repo is public. Never `git add -A` here.

Do not touch `app.py`. The daily run pushes straight to `master`, and `app.py` is not allowed on
`master` (it goes via a feature branch and a PR the user merges — see `CLAUDE.md`). A pre-push
hook rejects it, which would block the whole daily push.

## 5. Report

One short paragraph: how many companies were checked, how many briefs were published, and anything skipped or failed and why.
