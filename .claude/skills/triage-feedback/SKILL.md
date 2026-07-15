---
name: triage-feedback
description: Scan open GitHub feedback issues and triage each one — draft a local implementation proposal for valuable functionality issues, auto-close low-value ones with a fixed reply, or draft short answer to a general question awaiting approval. Use when asked to triage feedback, check the feedback queue, or review feedback issues.
---

# Triage feedback

The feedback button in `app.py` POSTs every submission as a GitHub issue labeled `feedback` on
`KatarzynaSzmydki/product-launch-newsfeed`, with no sub-type — title and body are free text.
This skill classifies each open one and routes it, using GitHub labels (not a local state file)
to track what's already been handled.

Never post a comment to GitHub in this skill except in the fixed low-value-close case below.
Everything else is staged locally and waits for a separate, explicit ask.

## 1. List candidates

```
gh issue list --repo KatarzynaSzmydki/product-launch-newsfeed --label feedback --state open --json number,title,body,createdAt,labels
```

Drop any issue whose `labels` already include `pending-approval`, `answered`, or
`triage:reviewed` — those have already been triaged. If nothing remains, report "0 issues to
triage" and stop.

## 2. Classify each remaining issue

- **Functionality-related** — a bug report, broken behavior, or a concrete feature/UX request
  about the app itself.
- **General question** — anything else (how something works, why a figure looks a certain way,
  a broader ask not about a defect or feature).

## 3. Functionality issues — assess value, then act

Weigh it against `product-launch-tracker-scope.md`, especially §2's non-goals (no forecasting,
no causal claims, mandatory disclaimer — a request that conflicts with a stated non-goal is
automatically low-value), plus whether it's already covered, feasible given the existing
mechanical/LLM-split architecture, or a duplicate of another open issue.

**Adds value** → write `data/pending_triage/<number>_plan.md` (issue link/title, problem
summary, proposed approach, affected files), then:
```
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --add-label triage:reviewed
```
Do not comment, do not close. The issue stays open; the plan is purely local until the user
decides to act on it.

**Doesn't add value** → close it immediately with this exact fixed comment (hardcoded here,
never regenerated per issue — that's what makes it safe to ship with no approval step):

```
gh issue close <number> --repo KatarzynaSzmydki/product-launch-newsfeed --comment "Thanks for taking the time to share this! After review, this doesn't fit where we're taking the app right now, so I'm closing it out. If you think we misread the request or there's more context that changes things, feel free to reopen or leave another note."
```

No extra label is needed — closed issues are already excluded from future `--state open` listings.

## 4. General questions — draft, stage, wait

Write the drafted short reply to `data/pending_triage/<number>_reply.md`, then:
```
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --add-label pending-approval
```
Never post it in this step, regardless of how confident the draft is — publishing is a
separate, explicit step (below), initiated by the user per issue.

## 5. Report

One digest: per issue, its number, title, classification, and the action taken — closed with
the fixed template, plan drafted at `<path>`, or reply staged at `<path>` awaiting approval.
No git commit is implied here — label edits and issue-closes hit GitHub directly, not this
repo's git history.

## Publishing an approved reply (separate, user-initiated per issue)

When told to post the reply for a specific issue (e.g. "post the reply for issue #7"):
```
gh issue comment <number> --repo KatarzynaSzmydki/product-launch-newsfeed --body-file data/pending_triage/<number>_reply.md
gh issue edit <number> --repo KatarzynaSzmydki/product-launch-newsfeed --remove-label pending-approval --add-label answered
```
Then delete `data/pending_triage/<number>_reply.md`. This is never done as part of a triage
run — only on explicit per-issue approval.
