# Checkpoint Parameter Reference

This document summarizes the parameters that affect checkpoint generation in this repository. It is grouped by entrypoint and by parameter type so it is easy to answer two practical questions:

1. What can I set directly right now?
2. What is currently fixed in code and would require a code change to tune?

## Scope

There are two main ways to generate checkpoints here:

- `checkpoint_scripts/run_single_bin_checkpoint.py`
  Runs `profiling -> cluster -> checkpoint` directly from an existing GCPT-bootable bin. This path always uses NEMU.
- `checkpoint_scripts/generate_checkpoint.py`
  Runs the full build plus checkpoint flow from YAML config.

## 1. Single-Bin Command-Line Parameters

Entrypoint:
- `checkpoint_scripts/run_single_bin_checkpoint.py`

### `--bin`

- Category: input path
- Purpose: path to the input GCPT-bootable bin file
- Required: yes
- Effective range:
  - Must be a readable file path
- Validation:
  - File must exist
  - File must be readable

### `--name`

- Category: workload identity
- Purpose: logical workload name; also used in output directory names
- Required: yes
- Effective range:
  - Any non-empty string
- Validation:
  - Must not be empty or whitespace only

### `--archive-id`

- Category: output naming
- Purpose: target archive directory name under `archive/`
- Required: no
- Effective range:
  - Any string that is valid as a directory name in the local filesystem
- Default behavior:
  - If omitted, the script generates `single_bin_nemu_<workload>_<timestamp>`

### `--interval`

- Category: checkpoint sampling
- Purpose: interval used by profiling and checkpoint stages
- Required: no
- Default:
  - `20000000`
- Effective range:
  - Integer greater than `0`
- Notes:
  - This value is forwarded to `--cpt-interval`

### `--copies`

- Category: execution topology
- Purpose: core count passed into the checkpoint flow
- Required: no
- Default:
  - `1`
- Effective range:
  - Integer greater than or equal to `1`
- Suggested range:
  - The repository README suggests keeping this below `4` in the current environment when running multi-copy flows

### `--resume-after`

- Category: resume control
- Purpose: skip earlier stages and continue from an existing result
- Required: no
- Effective range:
  - `profiling`
  - `cluster`
- Notes:
  - `profiling` requires an existing `profiling-0/<workload>/simpoint_bbv.gz`
  - `cluster` requires existing `cluster-0-0/<workload>/simpoints0` and `weights0`

## 2. Full-Flow YAML Parameters

Entrypoint:
- `checkpoint_scripts/generate_checkpoint.py`

Config examples:
- `checkpoint_scripts/config.yaml`
- `checkpoint_scripts/config_full_flow.yaml`
- `correct-config.yaml`

### Workload Selection

#### `base_config.spec_app_list`

- Category: workload selection
- Purpose: path to a text file containing workload names, one per line
- Effective range:
  - `null`
  - Existing text file path
- Notes:
  - Takes precedence over `spec_apps`

#### `base_config.spec_apps`

- Category: workload selection
- Purpose: comma-separated workload names
- Effective range:
  - `null`
  - Comma-separated string such as `"cactusADM,tonto"`

#### `base_config.custom_app_json`

- Category: workload metadata
- Purpose: use a custom app description file instead of the built-in SPEC app metadata
- Effective range:
  - `null`
  - Existing JSON/YAML file path

#### `base_config.CPU2017`

- Category: workload metadata
- Purpose: switch between SPEC CPU2006 and SPEC CPU2017 metadata sets
- Effective range:
  - `true`
  - `false`

### Flow Shape and Repetition

#### `base_config.times`

- Category: phase repetition
- Purpose: number of runs for `profiling,cluster,checkpoint`
- Effective range:
  - String of the form `"p,c,k"`
  - Each component should be a non-negative integer
- Common value:
  - `"1,1,1"`
- Notes:
  - The code expands this into a cartesian product of phase ids

#### `base_config.start_id`

- Category: phase indexing
- Purpose: starting ids for `profiling,cluster,checkpoint`
- Effective range:
  - String of the form `"p,c,k"`
  - Each component should be a non-negative integer
- Common value:
  - `"0,0,0"`

#### `base_config.archive_id`

- Category: archive reuse
- Purpose: reuse an existing archive instead of building a new one from scratch
- Effective range:
  - `null`
  - String
- Notes:
  - `null` means create a new archive id
  - Non-null means skip the build-preparation stage and continue from that archive

#### `base_config.max_threads`

- Category: parallelism
- Purpose: upper bound for concurrent workers during build/execution orchestration
- Effective range:
  - Positive integer

### Emulator and Checkpoint Behavior

#### `base_config.emulator`

- Category: simulator selection
- Purpose: simulator used for profiling and checkpoint stages
- Effective range:
  - `QEMU`
  - `NEMU`

#### `base_config.copies`

- Category: topology / parallel copies
- Purpose: number of copies or cores used in workload generation and checkpoint flow
- Effective range:
  - Integer greater than or equal to `1`
- Suggested range:
  - README currently suggests keeping this below `4` in the current environment
- Notes:
  - The kernel placement also changes when `copies == 1` versus `copies > 1`

#### `base_config.all_in_one_workload`

- Category: workload packaging
- Purpose: whether the workload is linked into an all-in-one GCPT image
- Effective range:
  - `true`
  - `false`
- Important constraint:
  - When using QEMU, this must be `true`

#### `base_config.bootloader`

- Category: boot stack
- Purpose: select the bootloader path
- Effective range:
  - `opensbi`
  - `riscv-pk`
- Practical note:
  - The repository currently documents `opensbi` as the maintained path

#### `base_config.enable_h_ext`

- Category: architecture features
- Purpose: enable H extension during build
- Effective range:
  - `true`
  - `false`

#### `base_config.boot_for_test`

- Category: validation
- Purpose: boot-test the generated image after build
- Effective range:
  - `true`
  - `false`

#### `base_config.redirect_output`

- Category: runtime I/O
- Purpose: redirect workload output in generated run scripts
- Effective range:
  - `true`
  - `false`

### Build Controls

#### `base_config.elf_folder`

- Category: input artifacts
- Purpose: source directory for ELF inputs
- Effective range:
  - Existing directory path

#### `base_config.build_bbl_only`

- Category: flow cutoff
- Purpose: stop after workload build
- Effective range:
  - `true`
  - `false`

#### `base_config.generate_rootfs_script_only`

- Category: flow cutoff
- Purpose: stop after generating rootfs scripts
- Effective range:
  - `true`
  - `false`

#### `base_config.cpu_bind`

- Category: NUMA / placement
- Purpose: forwarded to `numactl --cpunodebind`
- Effective range:
  - Integer-like string or integer accepted by `numactl`
- Practical note:
  - README currently labels this as effectively unused

#### `base_config.mem_bind`

- Category: NUMA / placement
- Purpose: forwarded to `numactl --membind`
- Effective range:
  - Integer-like string or integer accepted by `numactl`
- Practical note:
  - README currently labels this as effectively unused

### Archive Naming Metadata

These fields affect archive naming, not checkpoint semantics directly.

#### `archive_id_config.gcc_version`

- Category: archive metadata
- Effective range:
  - String

#### `archive_id_config.riscv_ext`

- Category: archive metadata
- Effective range:
  - String

#### `archive_id_config.base_or_fixed`

- Category: archive metadata
- Effective range:
  - String

#### `archive_id_config.special_flag`

- Category: archive metadata
- Effective range:
  - String

#### `archive_id_config.group`

- Category: archive metadata
- Effective range:
  - String

## 3. Required Environment Variables

These are not command-line or YAML parameters, but they are required to run the flows successfully.

### Single-bin path

#### `NEMU_HOME`

- Category: environment
- Purpose: locate the NEMU binary and SimPoint executable
- Effective range:
  - Must be set
  - Must point to an existing directory
- Required contents:
  - `build/riscv64-nemu-interpreter`
  - `resource/simpoint/simpoint_repo/bin/simpoint`

### Full-flow path

Depending on flow options, the code may require:

- `NEMU_HOME`
- `QEMU_HOME`
- `LINUX_HOME`
- `OPENSBI_HOME`
- `GCPT_HOME`
- `RISCV_ROOTFS_HOME`
- `XIANGSHAN_FDT`
- `CPU2006_RUN_DIR`
- `CPU2017_RUN_DIR`

The exact set depends on bootloader, emulator, and build path selection.

## 4. Internal Parameters That Affect Checkpoint Behavior but Are Currently Fixed in Code

These values matter, but you cannot tune them directly through the current CLI or YAML surface.

### SimPoint Clustering Parameters

Source:
- `checkpoint_scripts/take_checkpoint.py`

#### `maxK`

- Category: clustering
- Purpose: maximum number of clusters SimPoint may consider
- Current values:
  - `30` for most workloads
  - `100` for `xalancbmk`
- Effective range:
  - Positive integer
- Current tunability:
  - Hard-coded

#### `numInitSeeds`

- Category: clustering
- Purpose: number of SimPoint initialization seeds
- Current value:
  - `2`
- Effective range:
  - Positive integer
- Current tunability:
  - Hard-coded

#### `iters`

- Category: clustering
- Purpose: maximum SimPoint iterations
- Current value:
  - `1000`
- Effective range:
  - Positive integer
- Current tunability:
  - Hard-coded

#### `seedkm`

- Category: clustering randomness
- Purpose: random seed for clustering
- Current value:
  - Random integer in `[100000, 999999]`
- Effective range:
  - Integer in that closed interval
- Current tunability:
  - Hard-coded random generation

#### `seedproj`

- Category: clustering randomness
- Purpose: random seed for projection
- Current value:
  - Random integer in `[100000, 999999]`
- Effective range:
  - Integer in that closed interval
- Current tunability:
  - Hard-coded random generation

### Checkpoint Format

#### `compile_format`

- Category: output encoding
- Purpose: compression/format used for generated checkpoints
- Current value:
  - `zstd`
- Effective range:
  - Whatever the underlying runtime supports
- Current tunability:
  - Defaulted in code, not currently exposed in YAML or CLI

### QEMU Runtime Parameters

These affect QEMU-based profiling/checkpoint runs and are currently fixed in code.

#### QEMU memory

- Category: QEMU runtime
- Purpose: guest memory size
- Current value:
  - `8G`
- Current tunability:
  - Fixed in code

#### QEMU CPU string

- Category: QEMU runtime
- Purpose: select ISA and extensions
- Current value:
  - `rv64,v=true,vlen=128,h=false,sv39=true,sv48=false,sv57=false,sv64=false`
- Current tunability:
  - Fixed in code

#### `checkpoint-mode`

- Category: checkpoint policy
- Purpose: select the QEMU checkpoint mode
- Current value:
  - `SimpointCheckpoint`
- Current tunability:
  - Fixed in code

### Single-Bin Flow Fixed Batch Shape

These are fixed in the single-bin path today:

- `start_id = "0,0,0"`
- `times = "1,1,1"`
- `cpu_bind = "0"`
- `mem_bind = "0"`
- `all_in_one_workload = true`

That means the single-bin path always generates:

- `profiling-0`
- `cluster-0-0`
- `checkpoint-0-0-0`

## 5. Practical Priorities

If your goal is simply to control checkpoint behavior in everyday use, the most important knobs are:

- `--interval`
- `--copies`
- `--resume-after`
- `base_config.spec_apps` or `base_config.spec_app_list`
- `base_config.emulator`
- `base_config.times`
- `base_config.archive_id`

If you need deeper tuning of clustering quality or reproducibility, the next parameters worth exposing in code would be:

- `maxK`
- `numInitSeeds`
- `iters`
- `seedkm`
- `seedproj`
- `compile_format`
