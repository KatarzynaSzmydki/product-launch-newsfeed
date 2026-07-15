---
name: triage-feedback
description: Scan open GitHub feedback issues and triage each one — draft a local implementation proposal for valuable functionality issues, auto-close low-value ones with a fixed reply, or draft short answer to a general question awaiting approval. Use when asked to triage feedback, check the feedback queue, or review feedback issues.
---

# Triage feedback

The feedback button in `app.py` POSTs every submission as a GitHub issue labeled `feedback` on
`KatarzynaSzmydki/product-launch-newsfeed`, with no sub-type — title and body are free text.
This skill classifies each open one and routes it, using GitHub labels (not a local state file)
to track what's already been handled.

Never post a comment to GitHub in this skill except in the fixed low-value-close and
declined-proposal cases below. Everything else is staged as a file under `data/pending_triage/`
and waits for a separate, explicit ask.

## Committing staging files

`data/pending_triage/` is tracked in git (no longer git-ignored), because this skill runs
scheduled/headless: a plan or reply written only to the run's own sandbox never reaches the
user's checkout — that's a real bug we hit (issue #13's plan was lost this way). So the files
this skill writes and deletes must be committed and pushed. This is the one place the skill
touches this repo's git history; it goes straight to `master`, no PR (see `CLAUDE.md` — staging
output is exempt from the branch+PR rule). Always scope the add to the folder —
`git add data/pending_triage` (which also stages deletions in that path); never `git add -A`,
because `data/pending_generation/` is still ignored and must never be committed.

**Automatic run — one commit at the very end, then label.** Don't commit per issue. Do all the
file work first (the sync deletions in step 1, the drafted plans in step 4, the drafted replies
in step 5) and hold off on the gating labels. When every issue has been processed:

1. `git add data/pending_triage`
2. `git commit -m "Triage run: <n> plans, <m> replies, <k> stale removed"` — skip if nothing is
   staged.
3. `git pull --rebase && git push`
4. **Only after the push succeeds**, apply the gating labels — `triage:reviewed` for each drafted
   plan (step 4), `pending-approval` for each drafted reply (step 5). The exact `gh issue edit`
   commands are in those steps.

This ordering is deliberate: the gating label is what makes a future run skip an issue, so a file
must be committed *before* its label exists. If the run is interrupted before the end-commit,
nothing was labeled and nothing was committed, so the next run re-processes those issues cleanly.
(The low-value close in step 4 and its fixed comment hit GitHub directly and have no staged file,
so they can happen inline as you go.)

**Ad-hoc single-issue actions** (publishing a reply, declining a proposal) each change exactly one
file — commit that one change immediately, no batching:

```
git add data/pending_triage
git commit -m "Triage: <what changed> for issue #<n>"
git pull --rebase && git push
```

Use `git rm` (or the folder-scoped `git add`) for a deletion.

## 1. Sync already-reviewed issues

A `triage:reviewed` issue that's since been closed means its proposal was acted on — either
implemented (a PR with a closing keyword merged and auto-closed it) or explicitly declined (see
"Decline a proposal" below, which closes it itself). Either way the staged plan is stale:

```
gh issue list --repo KatarzynaSzmydki/product-launch-newsfeed --label triage:reviewed --state closed --json number
```

For each `<number>` returned, delete `data/pending_triage/<number>_plan.md` if it exists. Don't
commit the deletion here — it's part of the run's single end-of-run commit (see "Committing
staging files" above). These files are tracked, so a local delete alone would be resurrected on
the next `git pull`, which is exactly why the deletion must reach that commit.

## 2. List candidates

```
gh issue list --repo KatarzynaSzmydki/product-launch-newsfeed --label feedback --state open --json number,title,body,createdAt,labels
```

Drop any issue whose `labels` already include `pending-approval`, `answered`, or
`triage:reviewed` — those have already been triaged. If nothing remains, report "0 issues to
triage" and stop.

## 3. Classify each remaining issue

- **Functionality-related** — a bug report, broken behavior, or a concrete feature/UX request
  about the app itself.
- **General question** — anything else (how something works, why a figure looks a certain way,
  a broader ask not about a defect or feature).

## 4. Functionality issues — assess value, then act

Weigh it against `product-launch-tracker-scope.md`, especially §2's non-goals (no forecasting,
no causal claims, mandatory disclaimer — a request that conflicts with a stated non-goal is
automatically low-value), plus whether it's already covered, feasible given the existing
mechanical/LLM-split architecture, or a duplicate of another open issue.

**Adds value** → write `data/pending_triage/<number>_plan.md` (issue link/title, problem
summary, proposed approach, affected files). Don't commit it now, and don't label the issue yet —
the plan is committed in the run's single end-of-run commit, and only after that push succeeds do
you apply the label (see "Committing staging files"):
```
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --add-label triage:reviewed
```
Do not comment, do not close. The issue stays open; the plan is staged until the user decides to
act on it.

**Doesn't add value** → close it immediately with this exact fixed comment (hardcoded here,
never regenerated per issue — that's what makes it safe to ship with no approval step):

```
gh issue close <number> --repo KatarzynaSzmydki/product-launch-newsfeed --comment "Thanks for taking the time to share this! After review, this doesn't fit where we're taking the app right now, so I'm closing it out. If you think we misread the request or there's more context that changes things, feel free to reopen or leave another note."
```

No extra label is needed — closed issues are already excluded from future `--state open` listings.

## 5. General questions — draft, stage, wait

Write the drafted short reply to `data/pending_triage/<number>_reply.md`. Don't commit it now, and
don't label the issue yet — the reply is committed in the run's single end-of-run commit, and only
after that push succeeds do you apply the label (see "Committing staging files"):
```
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --add-label pending-approval
```
Never post it in this step, regardless of how confident the draft is — publishing is a
separate, explicit step (below), initiated by the user per issue.

## 6. Report

One digest: per issue, its number, title, classification, and the action taken — closed with
the fixed template, plan drafted at `<path>`, or reply staged at `<path>` awaiting approval.
All staged files were committed and pushed in one end-of-run commit, and the gating labels were
applied afterward (see "Committing staging files"); the low-value close and its fixed comment hit
GitHub directly, not this repo's git history.

## Review pending items (on demand, not part of the automatic run)

Invoked separately from the steps above (e.g. "what's waiting in triage?", "show me the pending
plans"). The committed `data/pending_triage/` folder is the queue — read it directly, don't
re-query GitHub or re-classify anything:

- List `data/pending_triage/*.md`. The suffix is the type: `<n>_plan.md` is a drafted
  implementation proposal (issue is `triage:reviewed`); `<n>_reply.md` is a drafted answer to a
  general question (issue is `pending-approval`).
- `Read` each file and present one digest, grouped by type — each file already embeds its issue
  link/title, so no GitHub call is needed just to list. For plans, surface the problem, proposed
  approach, and affected files; for replies, the question and the drafted answer.
- Then **stop and wait.** This section decides nothing on its own — it only surfaces what's
  awaiting a human call.

When the user acts on an item, route to the matching section below (each already handles the
GitHub write and the committed file deletion):

- `<n>_reply.md` → **Publishing an approved reply** (or discard: delete the file and commit the
  deletion, no GitHub post).
- `<n>_plan.md`, implement → **Implementing an approved proposal**.
- `<n>_plan.md`, decline → **Declining a proposal**.

## Publishing an approved reply (separate, user-initiated per issue)

When told to post the reply for a specific issue (e.g. "post the reply for issue #7"):
```
gh issue comment <number> --repo KatarzynaSzmydki/product-launch-newsfeed --body-file data/pending_triage/<number>_reply.md
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --remove-label pending-approval --add-label answered
```
Then delete `data/pending_triage/<number>_reply.md` and commit the deletion (see "Committing
staging files"). This is never done as part of a triage run — only on explicit per-issue
approval.

## Declining a proposal (separate, user-initiated per issue)

When told to decline a functionality proposal (e.g. "decline the proposal for issue #6"):
```
gh issue close <number> --repo KatarzynaSzmydki/product-launch-newsfeed --comment "Change declined by the owner."
```
Then delete `data/pending_triage/<number>_plan.md` immediately and commit the deletion (see
"Committing staging files") — don't wait for the next triage run's sync step. Never done as part
of an automatic triage run; deciding to decline is always a human call.

## Implementing an approved proposal

Build from the saved `data/pending_triage/<number>_plan.md` — that committed file is the spec
(problem, approach, affected files). Don't re-triage or re-plan the issue from scratch; the
plan was already reviewed and approved, so the implementation starts from it.

When a proposal is built, make sure the PR body closes every issue it resolves with its own
closing keyword — `Fixes #4, fixes #6`, not `Fixes #4 and #6` (GitHub only recognizes a
keyword immediately before each issue number; a bare number after "and"/a comma won't
auto-close). On merge, GitHub closes those issues, and the next triage run's sync step (above)
picks up the now-closed `triage:reviewed` issues and deletes their stale plan files.
