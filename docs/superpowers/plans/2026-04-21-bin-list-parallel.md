# Bin List Parallel Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-controlled parallel workload execution for `--bin-list` runs, with `max_workers` exposed in both the local CLI and GitHub Action.

**Architecture:** Extend the existing batch runner rather than changing the single-workload pipeline. Batch mode will submit isolated per-workload jobs through a thread pool, collect results centrally, and assign NUMA nodes in a simple round-robin pattern to reduce NEMU contention.

**Tech Stack:** Python `argparse`, Python `concurrent.futures`, GitHub Actions YAML, `unittest`

---

### Task 1: Add failing tests for the new batch parallel interface

**Files:**
- Modify: `tests/test_run_single_bin_checkpoint.py`
- Modify: `tests/test_checkpoint_workflow.py`

- [ ] **Step 1: Write the failing CLI/unit tests**

```python
def test_parse_args_accepts_max_workers(self):
    parser = single_bin.build_arg_parser()
    args = parser.parse_args(
        ["--bin-list", "/tmp/list.txt", "--max-workers", "3"]
    )
    self.assertEqual(args.max_workers, 3)

def test_validate_input_args_rejects_non_positive_max_workers(self):
    with self.assertRaisesRegex(ValueError, "max-workers"):
        single_bin.validate_input_args(
            Namespace(
                bin=None,
                bin_list="/tmp/list.txt",
                name=None,
                archive_id=None,
                interval=20000000,
                copies=1,
                resume_after=None,
                max_workers=0,
            )
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_run_single_bin_checkpoint`
Expected: FAIL because `max_workers` is not defined in the parser/validation flow.

- [ ] **Step 3: Write the failing workflow tests**

```python
self.assertIn("max_workers", inputs)
self.assertEqual(inputs["max_workers"]["default"], "3")
self.assertIn('MAX_WORKERS="${{ github.event.inputs.max_workers }}"', run_script)
self.assertIn('--max-workers "$MAX_WORKERS"', run_script)
```

- [ ] **Step 4: Run the workflow test to verify it fails**

Run: `python3 -m unittest tests.test_checkpoint_workflow`
Expected: FAIL because the workflow does not yet expose or forward `max_workers`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_run_single_bin_checkpoint.py tests/test_checkpoint_workflow.py
git commit -m "test: cover batch max_workers interface"
```

### Task 2: Add failing tests for parallel batch scheduling and worker placement

**Files:**
- Modify: `tests/test_run_single_bin_checkpoint.py`

- [ ] **Step 1: Write the failing executor-based scheduling test**

```python
with mock.patch.object(single_bin.concurrent.futures, "ThreadPoolExecutor") as pool_cls:
    pool = pool_cls.return_value.__enter__.return_value
    future_a = mock.Mock()
    future_b = mock.Mock()
    pool.submit.side_effect = [future_a, future_b]
    with mock.patch.object(single_bin.concurrent.futures, "as_completed", return_value=[future_a, future_b]):
        with mock.patch.object(single_bin, "run_single_checkpoint"):
            exit_code = single_bin.main()

    self.assertEqual(pool.submit.call_count, 2)
```

- [ ] **Step 2: Add the worker-placement expectation**

```python
pool.submit.assert_has_calls(
    [
        mock.call(
            single_bin.run_single_checkpoint,
            bin_path=str(alpha_bin),
            workload_name="alpha.bin",
            archive_id=None,
            interval=20000000,
            copies=2,
            resume_after=None,
            cpu_bind="0",
            mem_bind="0",
        ),
        mock.call(
            single_bin.run_single_checkpoint,
            bin_path=str(beta_bin),
            workload_name="beta.bin",
            archive_id=None,
            interval=20000000,
            copies=2,
            resume_after=None,
            cpu_bind="1",
            mem_bind="1",
        ),
    ]
)
```

- [ ] **Step 3: Run the batch test to verify it fails**

Run: `python3 -m unittest tests.test_run_single_bin_checkpoint`
Expected: FAIL because batch execution is still serial and `run_single_checkpoint` does not accept placement arguments.

- [ ] **Step 4: Commit**

```bash
git add tests/test_run_single_bin_checkpoint.py
git commit -m "test: cover parallel batch scheduling"
```

### Task 3: Implement CLI and workflow support for `max_workers`

**Files:**
- Modify: `checkpoint_scripts/run_single_bin_checkpoint.py`
- Modify: `.github/workflows/checkpoint-trigger.yml`
- Modify: `README.md`

- [ ] **Step 1: Add `--max-workers` to the Python CLI**

```python
parser.add_argument(
    "--max-workers",
    type=int,
    default=3,
    help="Maximum parallel workloads used by --bin-list mode",
)
```

- [ ] **Step 2: Validate the new argument**

```python
if args.max_workers < 1:
    raise ValueError("--max-workers must be at least 1")
```

- [ ] **Step 3: Add the workflow input and pass-through**

```yaml
      max_workers:
        description: Maximum parallel workloads used in batch mode
        required: false
        default: "3"
        type: string
```

```bash
MAX_WORKERS="${{ github.event.inputs.max_workers }}"
if [[ ! "$MAX_WORKERS" =~ ^[0-9]+$ ]] || [[ "$MAX_WORKERS" -le 0 ]]; then
  echo "ERROR: max_workers must be a positive integer, got: $MAX_WORKERS"
  exit 1
fi
```

```bash
bash run_single_bin_checkpoint.sh \
  --bin-list "$BIN_LIST_PATH" \
  --interval "$INTERVAL" \
  --max-workers "$MAX_WORKERS"
```

- [ ] **Step 4: Document the new option**

```markdown
- `--max-workers`：批量模式的最大并行 workload 数，默认 `3`
- GitHub Action 也支持 `max_workers` 输入，默认 `3`
```

- [ ] **Step 5: Run the targeted tests to verify green**

Run: `python3 -m unittest tests.test_run_single_bin_checkpoint tests.test_checkpoint_workflow`
Expected: PASS for parser/workflow interface coverage, while scheduling tests may still fail until Task 4 completes.

- [ ] **Step 6: Commit**

```bash
git add checkpoint_scripts/run_single_bin_checkpoint.py .github/workflows/checkpoint-trigger.yml README.md
git commit -m "feat: add batch max_workers interface"
```

### Task 4: Implement parallel batch scheduling with NUMA-aware worker placement

**Files:**
- Modify: `checkpoint_scripts/run_single_bin_checkpoint.py`

- [ ] **Step 1: Extend `run_single_checkpoint` to accept placement inputs**

```python
def run_single_checkpoint(
    *,
    bin_path: str,
    workload_name: str,
    archive_id: str | None,
    interval: int,
    copies: int,
    resume_after: str | None,
    cpu_bind: str = "0",
    mem_bind: str = "0",
) -> dict[str, str | int]:
```

- [ ] **Step 2: Thread placement into `generate_command(...)`**

```python
root = generate_command(
    workload_folder=layout["gcpt_bins"],
    workload=workload_name,
    buffer=archive_root,
    bin_suffix="",
    emu="NEMU",
    log_folder=layout["logs"],
    cpu_bind=cpu_bind,
    mem_bind=mem_bind,
    copies=str(copies),
    config=config,
    resume_after=resume_after,
    all_in_one_workload=True,
)
```

- [ ] **Step 3: Add a helper for batch worker placement**

```python
def get_worker_bindings(index: int, numa_nodes: int = 2) -> tuple[str, str]:
    node = str(index % numa_nodes)
    return node, node
```

- [ ] **Step 4: Replace serial batch execution with a thread pool**

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
    future_to_entry = {}
    for index, entry in enumerate(entries):
        cpu_bind, mem_bind = get_worker_bindings(index)
        future = executor.submit(
            run_single_checkpoint,
            bin_path=entry["bin"],
            workload_name=entry["name"],
            archive_id=None,
            interval=args.interval,
            copies=args.copies,
            resume_after=None,
            cpu_bind=cpu_bind,
            mem_bind=mem_bind,
        )
        future_to_entry[future] = entry
```

- [ ] **Step 5: Collect successes and failures explicitly**

```python
results = []
failures = []
for future in concurrent.futures.as_completed(future_to_entry):
    entry = future_to_entry[future]
    try:
        results.append(future.result())
    except Exception as exc:
        failures.append((entry["name"], str(exc)))
```

```python
if failures:
    print("Batch failures:")
    for name, error in failures:
        print(f"- {name}: {error}")
    return 1
```

- [ ] **Step 6: Run the targeted scheduling test**

Run: `python3 -m unittest tests.test_run_single_bin_checkpoint`
Expected: PASS with executor submission and worker placement coverage.

- [ ] **Step 7: Commit**

```bash
git add checkpoint_scripts/run_single_bin_checkpoint.py
git commit -m "feat: parallelize bin-list checkpoint runs"
```

### Task 5: Verify the full regression surface

**Files:**
- Modify: `checkpoint_scripts/take_checkpoint.py`

- [ ] **Step 1: Apply NUMA binding to checkpoint execution**

```python
command = [
    "numactl",
    "--cpunodebind={}".format(config["cpu_bind"]),
    "--membind={}".format(config["mem_bind"]),
    config["NEMU"]["NEMU"],
    "{}/{}{}".format(
        config["utils"]["workload_folder"],
        config["utils"]["workload"],
        config["utils"]["bin_suffix"],
    ),
    "-D",
    config["utils"]["buffer"],
    "-w",
    config["utils"]["workload"],
    "-C",
    config["checkpoint"]["config"],
    "-b",
    "-S",
    simpoint_path,
    "--cpt-interval",
    config["utils"]["interval"],
    "--checkpoint-format",
    config["utils"]["compile_format"],
]
```

- [ ] **Step 2: Run the wrapper and regression suites**

Run: `python3 -m unittest tests.test_run_single_bin_wrapper tests.test_run_single_bin_checkpoint tests.test_checkpoint_workflow tests.test_build_script`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add checkpoint_scripts/take_checkpoint.py tests/test_run_single_bin_wrapper.py tests/test_run_single_bin_checkpoint.py tests/test_checkpoint_workflow.py tests/test_build_script.py README.md
git commit -m "test: verify parallel batch checkpoint flow"
```
