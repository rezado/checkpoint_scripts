# checkpoint_scripts

这个仓库现在只保留一件事：从已经可启动的 GCPT bin 生成 checkpoint。

输入可以是：
- 单个 bin 文件
- 一个包含多个 bin 文件的目录

多 bin 模式下，所有 workload 会汇总到同一个 archive 里，目录名默认是：
- `profiling`
- `cluster`
- `checkpoint`
- `logs`
- `metadata`
- `json`
- `gcpt_bins`

## 流程拆分

`checkpoint_scripts/` 目录下保留的脚本按步骤组织：

- `generate_checkpoint.py`
  总入口；负责识别输入、批量调度、resume、汇总 metadata
- `step_profiling.py`
  生成 BBV
- `step_cluster.py`
  运行 SimPoint 聚类
- `step_checkpoint.py`
  根据聚类点生成 checkpoint，并校验产物
- `step_metadata.py`
  生成 `json/*.json` 和 `checkpoint/checkpoint.lst`
  入口内部同时负责统一管理 archive/stage 路径，以及校验 `NEMU_HOME` 和运行时工具

## GitHub Action

优先推荐直接使用仓库里的 `Checkpoint` workflow。

常用输入：
- `input_path`
  必填；可以是单个 bin，也可以是目录
- `name`
  仅单文件模式可用；覆盖 workload 名
- `archive_id`
  可选；指定输出目录名，或在 resume 时指向已有 archive
- `interval`
  checkpoint 间隔，默认 `20000000`
- `max_workers`
  目录模式下的最大并行 workload 数，默认 `3`
- `resume_after`
  可选；`profiling`、`cluster`、`auto`
- `rebuild_nemu`
  可选；为 `true` 时先重编译 NEMU、`gcpt_restore` 和 `simpoint`

workflow timeout 目前是 14 天。

## 本地使用

先准备环境：

```bash
source /nfs/home/share/workload_env/env.sh
```

至少要保证：
- `NEMU_HOME` 已设置
- `$NEMU_HOME/build/riscv64-nemu-interpreter` 已存在
- `$NEMU_HOME/resource/simpoint/simpoint_repo/bin/simpoint` 已存在

单 bin：

```bash
python3 checkpoint_scripts/generate_checkpoint.py \
  --input-path /path/to/demo.fw_payload.bin \
  --name demo \
  --archive-id demo-checkpoint
```

多 bin：

```bash
python3 checkpoint_scripts/generate_checkpoint.py \
  --input-path /path/to/bin-directory \
  --interval 20000000 \
  --max-workers 3
```

resume：

```bash
python3 checkpoint_scripts/generate_checkpoint.py \
  --input-path /path/to/bin-directory \
  --archive-id checkpoint_batch_2026-05-17-12-00-00 \
  --resume-after auto
```

## 命名规则

- 单文件模式下，如果不传 `--name`，会从文件名自动去掉已知后缀后得到 workload 名
- 目录模式下，会根据所有文件名的公共后缀推导 workload 名
- 当前内置的常见后缀主要是 `.fw_payload.bin` 和 `.bin`

例如：
- `gcc_166.fw_payload.bin` -> `gcc_166`
- `astar_biglakes.bin` -> `astar_biglakes`

## 输出结构

以 `archive/checkpoint_batch_2026-05-17-12-00-00/` 为例：

```text
archive/checkpoint_batch_2026-05-17-12-00-00/
├── checkpoint/
├── cluster/
├── gcpt_bins/
├── json/
├── logs/
├── metadata/
└── profiling/
```

说明：
- `gcpt_bins/`
  保存输入 bin 的归档副本，方便 resume 和结果复现
- `metadata/`
  保存批量请求和每个 workload 的请求记录
- `json/`
  保存每个 workload 的 JSON，以及：
  - `checkpoints_all.json`
  - `checkpoints_cov0.3.json`
- `checkpoint/checkpoint.lst`
  汇总后的 checkpoint list

## 测试

当前测试覆盖的是这条精简后的 checkpoint 生成链：

```bash
python -m unittest \
  tests.test_step_metadata \
  tests.test_generate_checkpoint \
  tests.test_checkpoint_steps \
  tests.test_checkpoint_workflow
```
