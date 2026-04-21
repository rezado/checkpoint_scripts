# Bin List Parallel Batch Design

## Goal

Allow `run_single_bin_checkpoint.sh` and the GitHub Action batch entrypoint to run multiple workloads from `--bin-list` in parallel, with a user-controlled `max_workers` parameter and a default of `3`.

## Scope

- Add `max_workers` to the local batch CLI.
- Add `max_workers` to the GitHub Action `workflow_dispatch` inputs.
- Run multiple workloads from `--bin-list` concurrently.
- Preserve the existing single-workload execution order: `profiling -> cluster -> checkpoint`.
- Reduce NEMU interference by assigning batch workers to NUMA nodes in a predictable way.

## Non-Goals

- Splitting a single workload into parallel profiling or parallel checkpoint tasks.
- Refactoring the overall checkpoint pipeline architecture.
- Converting the GitHub Action to matrix jobs.

## Current Behavior

- `run_single_bin_checkpoint.py` processes `--bin-list` entries serially.
- Each workload already writes to an isolated archive directory, so file output is workload-local.
- NEMU profiling and simpoint clustering use `numactl`, but the current single-bin wrapper hardcodes `cpu_bind=0` and `mem_bind=0`.
- NEMU checkpoint execution currently does not apply NUMA binding.

## Desired Behavior

- `--bin-list` mode accepts `--max-workers`, default `3`.
- The GitHub Action accepts a matching `max_workers` input and forwards it to the script.
- Batch workloads are submitted concurrently and summarized after completion.
- Any workload failure is surfaced clearly, and the overall process exits non-zero.
- Worker resource placement is deterministic enough to avoid pushing all workloads onto NUMA node `0`.

## Design

### CLI and Workflow Interface

- Add `--max-workers` to `run_single_bin_checkpoint.py`.
- Keep the value valid for both `--bin` and `--bin-list`, but only use it for batch mode.
- Default `max_workers` to `3`.
- Extend `.github/workflows/checkpoint-trigger.yml` with a `max_workers` input, default `3`, validate it as a positive integer, and pass it through to `run_single_bin_checkpoint.sh`.

### Batch Execution Model

- Use `concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers)` in the `--bin-list` branch.
- Submit one future per workload, each calling `run_single_checkpoint(...)`.
- Preserve per-workload isolation by keeping each archive independent.
- Collect results from futures and print a final batch summary after all futures complete.
- Aggregate failures; if any future raises, print the failed workloads and return non-zero.

### NUMA Placement

- Add optional worker-placement parameters to `run_single_checkpoint(...)`.
- Compute worker placement in the batch scheduler using a simple round-robin node assignment:
  - worker index `0 -> node 0`
  - worker index `1 -> node 1`
  - worker index `2 -> node 0`
  - and so on
- Pass the selected node as both `cpu_bind` and `mem_bind`.
- Apply the same binding consistently to profiling, cluster, and checkpoint NEMU execution.

### Testing

- Add unit coverage for the new wrapper/CLI behavior:
  - `max_workers` argument parsing and validation
  - workflow input exposure and pass-through
  - batch mode using executor-based parallel submission instead of serial direct calls
  - worker placement being forwarded into `run_single_checkpoint(...)`

## Risks

- Parallel workloads will still compete for shared CPU, memory bandwidth, and filesystem throughput; NUMA-aware placement only reduces contention, it does not eliminate it.
- Log lines from the batch driver may interleave, but per-workload archive logs remain isolated.
- If a workload is much longer than others, total batch wall time will still be dominated by the slowest workload.

## Acceptance Criteria

- `run_single_bin_checkpoint.sh --bin-list ... --max-workers 3` runs workloads concurrently.
- The GitHub Action can be triggered with a `max_workers` input and forwards it correctly.
- A user-specified NEMU path remains respected during batch runs.
- Parallel runs still produce per-workload archive outputs with no path collisions.
- Test coverage exists for the new CLI and workflow surface area.
