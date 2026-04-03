# GitHub Action Interval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GitHub Actions single-bin checkpoint workflow accept a configurable checkpoint interval and pass it through to the runtime script.

**Architecture:** Add a new `workflow_dispatch` input named `interval`, validate it in the shell step, and forward it to `run_single_bin_checkpoint.sh`. Cover the workflow contract with a small unit test that parses the YAML and asserts the new input and command wiring are present.

**Tech Stack:** GitHub Actions YAML, Python 3, `unittest`, `PyYAML`

---

### Task 1: Add failing workflow contract test

**Files:**
- Create: `tests/test_checkpoint_workflow.py`
- Test: `tests/test_checkpoint_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
def test_workflow_dispatch_exposes_interval_input():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_checkpoint_workflow -v`
Expected: FAIL because the workflow does not expose or forward `interval` yet.

- [ ] **Step 3: Write minimal implementation**

```yaml
interval:
  description: Checkpoint interval
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_checkpoint_workflow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_checkpoint_workflow.py .github/workflows/checkpoint-trigger.yml README.md
git commit -m "feat: make checkpoint workflow interval configurable"
```
