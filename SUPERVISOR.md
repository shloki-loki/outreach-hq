# Outreach HQ shared supervisor

Updated 2026-11-14. This is the entry point whether Shlok speaks to Codex or Claude.
The assistant receiving his request acts as supervisor. Shlok should not relay messages between models.

## Start every session

1. Use a current checkout of the shared repository. Read AGENTS.md, HANDOFF.md, this file,
   config/routing.toml and config/voice.md. Never pull over another assistant's uncommitted work.
2. Run `python3 -m outreach supervisor`, `python3 -m outreach work list`, and
   `python3 -m outreach log list --limit 40`. Data commands require the data branch attached.
3. Check existing work before starting. Record the user's issue and desired outcome once.
4. Claim the item before working. Use `packet <lead>` to reuse saved evidence and drafts.
5. Diagnose, implement, test, open a PR for code/config, update the handoff, and complete the item
   with evidence. Do not call a PR deployed until it is merged and the deployed behavior is verified.

## Who does what

| Work | Preferred owner | Dependency |
|---|---|---|
| Collection, rule scoring, approved sending, reply tracking, digest | GitHub Python | No LLM |
| Deterministic supervisor checks | GitHub Python | No LLM; new workflow after merge |
| Research, personalization, application answers, follow-ups | Codex | An active Codex worker/session |
| Selective difficult-case or high-priority quality review | Claude | An active Claude worker/session |
| Engineering changes | Codex by default, either assistant can own | One branch and owner per change |
| User-facing supervisor | Whichever assistant Shlok is talking to | Same records and rules |
| Approval, application submission, LinkedIn sending | Shlok | Human action |

These are changeable defaults in config/routing.toml, not hardcoded model requirements.
Either assistant can reassign an unclaimed item with a recorded reason. Changing a default does not
silently move in-progress work. Release it with a useful handoff before assigning it elsewhere.
Do not use both models on every lead. Ask for a second review only when evidence or quality warrants it.

## Commands

```
python3 -m outreach work add --kind research --lead L0001 --title "Research and source a hook"
python3 -m outreach work claim --id W0001 --owner codex
python3 -m outreach packet L0001
python3 -m outreach work release --id W0001 --owner codex --detail "Facts saved; need pay evidence"
python3 -m outreach work assign --id W0001 --owner claude --detail "Codex unavailable; continue saved research"
python3 -m outreach work claim --id W0001 --owner claude
python3 -m outreach work done --id W0001 --owner claude --detail "Research saved and checked" --ref L0001
```

Work kinds: research, draft, followup, review, engineering. Claims last two hours. A second claim is refused
while active, even for the same provider. If it expires, stop the old worker before reclaiming and inspect
partial work. The queue coordinates cooperative workers; legacy data commands do not enforce claims.
Use one active worker session per provider/work item. This is not a distributed execution engine.

## Daily founder batch (60 emails a day, decided by Shlok 2026-11-15)

Shlok's founder list (983 companies, 1,931 checked addresses, source `founder_reoutreach`) is worked as 60
personal emails a day. Each is researched (one sourced hook), written to playbook v3 (`config/voice.md`)
and queued for his approval. Nothing is sent until he approves it on the site; the sender's daily cap is 60.

| Time (IST) | Who | What |
|---|---|---|
| 10:00 | Claude (scheduled) | `work founder-batch` queues today's 60 for codex; `work batch-status` |
| 12:15 | Codex/GPT (scheduled) | works the queue with `config/prompts/founder-email-worker.md` |
| 16:00 | Claude (scheduled) | `work handover --owner claude --from-owner codex --detail "..."` for anything codex has not started, then works it with the same prompt |
| later | Grok | when Shlok adds it: third in `routing.toml [fallback]`; same prompt, `--owner grok` |
| 18:00+ | supervisor report | alerts if the day's batch is not done |

Commands: `work founder-batch [--count N] [--owner X]`, `work next --owner X`, `work handover --owner X
[--from-owner Y] --detail "reason"`, `work batch-status`. Handover never takes an active claim.

## Application packet and personalization

The packet command combines existing research, sources, contacts, emails and application answers.
It flags missing information. It does not invent research or mark work factually verified.
For each lead, the assigned writer must deliver:
- one sourced company observation and why it matters for this role;
- one exact relevant achievement from profile.toml, expressed clearly;
- one strong email in voice.md's style, rather than several alternatives for Shlok to reconcile;
- answers to the actual application questions, within their limits, with unknown facts marked NEEDS SHLOK;
- clear missing items and the next action for Shlok.
Save answers through the existing `lead set --apply-answers` command and emails through `message draft`.
Company-specific claims must not be copied between companies. Reuse verified profile facts and approved
wording only. Capture Shlok's corrections as specific writing guidance, never invented biography.
Target 5–10 minutes of personal review/submission time; measure the first 20 packets and rewrite effort.
The packet is available in CLI output and at the top of each website lead page, with source links, draft preview, copyable answers and missing-item flags. A reusable approved-answer library remains pending.

## Improvements raised with either model

The receiving supervisor owns the request through resolution, within authorization. Record a work item,
check prior fixes, identify whether code, routing, evidence or writing instructions caused the problem,
then make the smallest tested change. Update shared instructions/config and the supervisor log so the
other model sees the improvement on its next sync. Include the PR/commit, validation and unfinished steps.
Never solve a systemic issue solely in private chat memory. Changes do not automatically propagate to
already-running sessions; those must reread the updated instructions before taking another item.
No automatic merging, arbitrary self-modification, credential transfer or new spending is introduced.

## Rollout and current limits

This change adds a real shared work queue, CLI packet assembler, routing configuration and deterministic
GitHub health workflow (08:45, 14:45, 20:45 IST). It does not start Codex/Claude model sessions.
No model credentials or paid APIs are configured. Existing Claude desktop schedules remain unchanged.
Before switching a scheduled writer to Codex: connect/verify that worker, require queue claims in its task
prompt, validate 20 packets, then disable the overlapping legacy task. Until then Claude remains the
scheduled writer, even though new manually queued work defaults to Codex.
The health check records missing/stale mechanical runs, failed/stuck messages and expired claims; it does
not replace every investigative supervisor task and does not repair code automatically.
GitHub Models is retired according to https://docs.github.com/en/github-models (checked 2026-11-14).
Full hosted model execution still requires a separately verified provider/account setup.
Sending approvals, caps, suppression, free-tier constraints and manual LinkedIn/application submission
remain binding. Playbook v2's pending validator work remains separately tracked in HANDOFF.md.

## Validation for this update

48 unit tests pass (45 existing plus three shared-supervisor scenarios covering claims, handoffs,
duplicate work, completion evidence, missing packets and expired leases). CLI help and diff whitespace
checks pass. Live scheduled execution and hosted model invocation have not been tested.

## Rollout update: 2026-11-14

PR #1 merged as a6e7d3f. The GitHub supervisor workflow was manually dispatched and completed
successfully (run 43584199808). Codex app heartbeat `outreach-hq-codex-worker` is active daily
at 12:15 IST and processes at most three explicitly assigned queued items. It does not take
unassigned leads or duplicate the Claude batch. This is a local app worker, not hosted GitHub
model execution, and requires the app/Mac to be available. Its first scheduled run remains
unverified. Claude's checkout was checked and synced to the shared instructions. Existing
Claude schedules remain active; the 20-packet evaluation is still required before replacement.
Website packet production build passes; 49 Python tests pass.
