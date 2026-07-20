# QA Cron Prompt Filtering Design

## Problem

OpenClaw stores isolated cron `agentTurn` prompts as `message` records with
`role=user`. The deterministic QA scanner currently treats every such record
as a customer message. A weekly reporting prompt therefore matched complaint
terms such as `unvollständig`, `fehlt`, and `failed` and produced a false high
severity finding.

## Scope

- Ignore automated cron prompts whose normalized text starts with `[cron:`.
- Continue scanning ordinary user messages without changing term matching or
  severity classification.
- Add regression tests for both the ignored cron prompt and a genuine user
  complaint.
- Do not modify live OpenClaw cron jobs, runtime databases, or historical
  reports.

## Design

Add a small predicate, `is_automated_prompt(text: str) -> bool`, and call it in
`scan_file` before keyword matching. The predicate trims leading whitespace
and compares case-insensitively so formatting differences do not reintroduce
the false positive.

An exact cron marker is deliberately preferred to a broad automation-prefix
blacklist: the observed provenance marker is deterministic, while broader
rules could suppress real customer messages.

## Verification

- A JSONL user record beginning with `[cron:` and containing strong complaint
  terms yields no findings.
- A normal JSONL user record containing `unvollständig` still yields one high
  severity finding.
- The scanner run over the reported 2026-07-20 time window returns
  `NO_FINDINGS` for the affected main-agent session.
- Root Python modules pass `python3 -m py_compile *.py`.
