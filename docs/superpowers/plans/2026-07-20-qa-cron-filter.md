# QA Cron Prompt Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent cron task instructions stored as user messages from becoming customer-complaint findings.

**Architecture:** Keep source classification inside `qa_interaction_scan.py`. A focused predicate recognizes the deterministic cron marker before the existing term matcher runs.

**Tech Stack:** Python 3 standard library, `unittest`, JSONL fixtures.

## Global Constraints

- Do not change complaint terms or severity rules.
- Do not suppress ordinary user messages.
- Do not modify live cron jobs, databases, or historical reports.

---

### Task 1: Add cron-source filtering

**Files:**
- Modify: `qa_interaction_scan.py`
- Create: `tests/test_qa_interaction_scan.py`

**Interfaces:**
- Consumes: extracted message text from `extract_text(content)`.
- Produces: `is_automated_prompt(text: str) -> bool`, used by `scan_file`.

- [ ] **Step 1: Write the failing regression test**

Create a temporary JSONL session containing a `role=user` cron prompt with
`unvollständig` and assert that `scan_file` returns no findings. Include a
second test proving that an ordinary complaint still returns a high finding.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_qa_interaction_scan -v`

Expected: the cron regression test fails because one finding is returned.

- [ ] **Step 3: Implement the minimal filter**

Add:

```python
def is_automated_prompt(text: str) -> bool:
    return text.lstrip().casefold().startswith("[cron:")
```

Call it after extracting non-empty text and before `matched_terms`.

- [ ] **Step 4: Run focused and repository verification**

Run:

```bash
python3 -m unittest tests.test_qa_interaction_scan -v
python3 qa_interaction_scan.py --agents main --since 2026-07-20T08:29:59Z --until 2026-07-20T08:31:00Z
python3 -m py_compile *.py
```

Expected: tests pass, the reproduction prints `NO_FINDINGS`, and compilation
exits successfully.
