import argparse
import concurrent.futures
import os
import shutil
from datetime import datetime

from checkpoint_postprocess import cluster_weight
from checkpoint_postprocess import generate_checkpoint_metadata
from take_checkpoint import TakeCheckpointConfig
from take_checkpoint import generate_command
from take_checkpoint import level_first_exec

COMPRESSED_CHECKPOINT_SUFFIXES = (".gz", ".zstd")


def build_archive_layout(archive_root: str) -> dict[str, str]:
    return {
        "buffer_path": archive_root,
        "gcpt_bins": os.path.join(archive_root, "gcpt_bins"),
        "logs": os.path.join(archive_root, "logs"),
        "metadata": os.path.join(archive_root, "metadata"),
    }


def ensure_directories(paths) -> None:
    for path in paths:
        os.makedirs(path, exist_ok=True)


def generate_archive_id(workload: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return f"single_bin_nemu_{workload}_{timestamp}"


def write_request_metadata(metadata_dir: str, request: dict) -> str:
    os.makedirs(metadata_dir, exist_ok=True)
    output_path = os.path.join(metadata_dir, "single_bin_request.yaml")
    lines = [
        f"bin: {request['bin']}",
        f"name: {request['name']}",
        f"archive_id: {request['archive_id']}",
        f"interval: {request['interval']}",
        f"copies: {request['copies']}",
        f"resume_after: {request['resume_after']}",
        f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
    ]
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return output_path


def validate_resume_artifacts(archive_root: str, workload: str,
                              resume_after: str | None) -> None:
    required = []
    if resume_after == "profiling":
        required = [
            os.path.join(archive_root, "profiling-0", workload,
                         "simpoint_bbv.gz")
        ]
    elif resume_after == "cluster":
        required = [
            os.path.join(archive_root, "cluster-0-0", workload, "simpoints0"),
            os.path.join(archive_root, "cluster-0-0", workload, "weights0"),
        ]

    for path in required:
        if not os.path.exists(path):
            raise FileNotFoundError(f"required resume artifact missing: {path}")


def validate_outputs(archive_root: str, workload: str) -> None:
    required = [
        os.path.join(archive_root, "profiling-0", workload, "simpoint_bbv.gz"),
        os.path.join(archive_root, "cluster-0-0", workload, "simpoints0"),
        os.path.join(archive_root, "cluster-0-0", workload, "weights0"),
    ]
    for path in required:
        if not os.path.exists(path):
            raise FileNotFoundError(f"expected output missing: {path}")

    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0", workload)
    if not os.path.isdir(checkpoint_dir):
        raise FileNotFoundError(
            f"expected checkpoint output directory missing: {checkpoint_dir}")

    checkpoint_count = sum(
        1 for root, _, files in os.walk(checkpoint_dir)
        for name in files if name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES))
    if checkpoint_count == 0:
        raise FileNotFoundError(
            f"no compressed checkpoint artifacts found under: {checkpoint_dir}")

    expected_points = cluster_weight(
        os.path.join(archive_root, "cluster-0-0"), workload)
    missing_points = []
    for point in sorted(expected_points):
        point_dir = os.path.join(checkpoint_dir, point)
        if not os.path.isdir(point_dir):
            missing_points.append(point)
            continue

        has_artifact = any(
            name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES)
            for name in os.listdir(point_dir))
        if not has_artifact:
            missing_points.append(point)

    if missing_points:
        raise FileNotFoundError(
            "missing compressed checkpoint artifacts for expected simpoints: "
            + ", ".join(missing_points))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=
        "Run profiling, cluster, and checkpoint from a single GCPT bin with NEMU"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--bin",
                             help="Path to a GCPT-bootable bin file")
    input_group.add_argument(
        "--bin-list",
        dest="bin_list",
        help="Path to a text file containing one GCPT-bootable bin path per line",
    )
    parser.add_argument("--name",
                        help="Workload name used with --bin")
    parser.add_argument("--archive-id", help="Existing or new archive id")
    parser.add_argument("--interval",
                        type=int,
                        default=20_000_000,
                        help="Checkpoint interval")
    parser.add_argument("--copies",
                        type=int,
                        default=1,
                        help="Core count passed to the checkpoint flow")
    parser.add_argument("--max-workers",
                        type=int,
                        default=3,
                        help="Maximum parallel workloads used by --bin-list mode")
    parser.add_argument("--resume-after",
                        choices=["profiling", "cluster"],
                        help="Resume from a later stage")
    return parser


def validate_input_args(args) -> None:
    if args.bin and args.bin_list:
        raise ValueError("provide exactly one of --bin or --bin-list")
    if not args.bin and not args.bin_list:
        raise ValueError("either --bin or --bin-list is required")

    if args.bin:
        if not os.path.isfile(args.bin):
            raise FileNotFoundError(f"input bin does not exist: {args.bin}")
        if not os.access(args.bin, os.R_OK):
            raise PermissionError(f"input bin is not readable: {args.bin}")
        if args.name is None or not args.name.strip():
            raise ValueError("--name is required when using --bin")
    else:
        if not os.path.isfile(args.bin_list):
            raise FileNotFoundError(
                f"bin list file does not exist: {args.bin_list}")
        if not os.access(args.bin_list, os.R_OK):
            raise PermissionError(
                f"bin list file is not readable: {args.bin_list}")
        if args.name is not None:
            raise ValueError("--name can only be used with --bin")
        if args.archive_id is not None:
            raise ValueError(
                "--archive-id cannot be used with --bin-list because each bin gets its own archive"
            )
        if args.resume_after is not None:
            raise ValueError(
                "--resume-after cannot be used with --bin-list because each bin runs in a fresh archive"
            )

    if args.copies < 1:
        raise ValueError("--copies must be at least 1")
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")
    if args.interval <= 0:
        raise ValueError("--interval must be a positive integer")


def validate_runtime_tools(nemu_home: str) -> None:
    required = [
        os.path.join(nemu_home, "build", "riscv64-nemu-interpreter"),
        os.path.join(nemu_home, "resource", "simpoint", "simpoint_repo", "bin",
                     "simpoint"),
    ]
    for path in required:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"required runtime tool missing: {path}")


def copy_input_bin(src: str, dst: str) -> str:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def ensure_resume_logs(archive_root: str, workload: str,
                       resume_after: str | None) -> None:
    if resume_after is None:
        return
    log_dir = os.path.join(archive_root, "logs", "profiling-0", workload)
    os.makedirs(log_dir, exist_ok=True)
    for name in ["profiling.out.log", "profiling.err.log"]:
        path = os.path.join(log_dir, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("")


def remove_path(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def reset_stage_outputs(archive_root: str, workload: str,
                        resume_after: str | None) -> None:
    if resume_after is None:
        stages_to_remove = ("profiling", "cluster", "checkpoint")
    elif resume_after == "profiling":
        stages_to_remove = ("cluster", "checkpoint")
    elif resume_after == "cluster":
        stages_to_remove = ("checkpoint",)
    else:
        raise ValueError(f"unsupported resume stage: {resume_after}")

    stage_paths = {
        "profiling": [
            os.path.join(archive_root, "profiling-0", workload),
            os.path.join(archive_root, "logs", "profiling-0", workload),
        ],
        "cluster": [
            os.path.join(archive_root, "cluster-0-0", workload),
            os.path.join(archive_root, "logs", "cluster-0-0", workload),
        ],
        "checkpoint": [
            os.path.join(archive_root, "checkpoint-0-0-0", workload),
            os.path.join(archive_root, "logs", "checkpoint-0-0-0", workload),
            os.path.join(archive_root, "checkpoint-0-0-0", "cluster-0-0.json"),
            os.path.join(archive_root, "checkpoint-0-0-0", "checkpoint.lst"),
        ],
    }

    for stage in stages_to_remove:
        for path in stage_paths[stage]:
            remove_path(path)


def count_checkpoints(archive_root: str, workload: str) -> int:
    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0", workload)
    return sum(
        1 for root, _, files in os.walk(checkpoint_dir)
        for name in files if name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES))


def build_single_run_args(bin_path: str, workload_name: str, archive_id: str | None,
                          interval: int, copies: int, max_workers: int,
                          resume_after: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        bin=bin_path,
        bin_list=None,
        name=workload_name,
        archive_id=archive_id,
        interval=interval,
        copies=copies,
        max_workers=max_workers,
        resume_after=resume_after,
    )


def get_worker_bindings(index: int, numa_nodes: int = 2) -> tuple[str, str]:
    node = str(index % max(1, numa_nodes))
    return node, node


def load_bin_list_entries(bin_list_path: str) -> list[dict[str, str]]:
    entries = []
    seen_names = set()

    with open(bin_list_path, "r", encoding="utf-8") as handle:
        for index, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            workload_name = os.path.basename(os.path.normpath(line))
            if not workload_name:
                raise ValueError(
                    f"unable to derive workload name from line {index}: {line}")
            if workload_name in seen_names:
                raise ValueError(
                    f"duplicate workload name derived from bin list: {workload_name}"
                )

            entries.append({"bin": line, "name": workload_name})
            seen_names.add(workload_name)

    if not entries:
        raise ValueError(
            f"bin list file does not contain any usable bin paths: {bin_list_path}"
        )

    return entries


def run_single_checkpoint(*, bin_path: str, workload_name: str,
                          archive_id: str | None, interval: int, copies: int,
                          resume_after: str | None, cpu_bind: str = "0",
                          mem_bind: str = "0") -> dict[str, str | int]:
    args = build_single_run_args(
        bin_path=bin_path,
        workload_name=workload_name,
        archive_id=archive_id,
        interval=interval,
        copies=copies,
        max_workers=1,
        resume_after=resume_after,
    )
    validate_input_args(args)

    resolved_archive_id = archive_id or generate_archive_id(workload_name)
    archive_root = os.path.realpath(os.path.join("archive", resolved_archive_id))
    layout = build_archive_layout(archive_root)
    ensure_directories(layout.values())

    request = {
        "bin": os.path.realpath(bin_path),
        "name": workload_name,
        "archive_id": resolved_archive_id,
        "interval": interval,
        "copies": copies,
        "resume_after": resume_after,
    }
    metadata_path = write_request_metadata(layout["metadata"], request)
    copied_bin = copy_input_bin(bin_path,
                                os.path.join(layout["gcpt_bins"],
                                             workload_name))

    reset_stage_outputs(archive_root, workload_name, resume_after)
    validate_resume_artifacts(archive_root, workload_name, resume_after)
    ensure_resume_logs(archive_root, workload_name, resume_after)

    nemu_home = os.environ.get("NEMU_HOME")
    if not nemu_home:
        raise EnvironmentError("NEMU_HOME is not set")
    validate_runtime_tools(nemu_home)

    take_config = TakeCheckpointConfig(start_id="0,0,0",
                                       times="1,1,1",
                                       path_env_vars_to_check=["NEMU_HOME"])
    config = take_config.get_config()
    config["utils"]["interval"] = str(interval)

    root = generate_command(workload_folder=layout["gcpt_bins"],
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
                            all_in_one_workload=True)
    if root is None:
        raise RuntimeError("failed to generate execution tree")

    print(f"Archive: {resolved_archive_id}")
    print(f"Input bin copied to: {copied_bin}")
    print(f"Metadata: {metadata_path}")
    print(f"Interval: {interval}")
    print(f"Copies: {copies}")
    print(f"CPU bind: {cpu_bind}")
    print(f"MEM bind: {mem_bind}")
    print(f"Resume after: {resume_after or 'fresh'}")

    level_first_exec(root)
    validate_outputs(archive_root, workload_name)
    generate_checkpoint_metadata(
        archive_root=archive_root,
        workloads=[workload_name],
        times=[1, 1, 1],
        ids=[0, 0, 0],
    )

    checkpoint_count = count_checkpoints(archive_root, workload_name)
    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0",
                                  workload_name)
    print(f"Checkpoint count: {checkpoint_count}")
    print(f"Checkpoint dir: {checkpoint_dir}")

    return {
        "name": workload_name,
        "archive_id": resolved_archive_id,
        "archive_root": archive_root,
        "checkpoint_count": checkpoint_count,
        "checkpoint_dir": checkpoint_dir,
    }


def main() -> int:
    args = build_arg_parser().parse_args()
    validate_input_args(args)

    if args.bin:
        run_single_checkpoint(bin_path=args.bin,
                              workload_name=args.name,
                              archive_id=args.archive_id,
                              interval=args.interval,
                              copies=args.copies,
                              resume_after=args.resume_after)
        return 0

    entries = load_bin_list_entries(args.bin_list)
    for entry in entries:
        validate_input_args(
            build_single_run_args(bin_path=entry["bin"],
                                  workload_name=entry["name"],
                                  archive_id=None,
                                  interval=args.interval,
                                  copies=args.copies,
                                  max_workers=args.max_workers,
                                  resume_after=None))

    print(f"Batch size: {len(entries)}")
    print(f"Max workers: {args.max_workers}")
    results = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.max_workers) as executor:
        future_to_entry = {}
        for index, entry in enumerate(entries):
            cpu_bind, mem_bind = get_worker_bindings(index)
            print(
                f"=== [{index + 1}/{len(entries)}] Checkpointing {entry['name']} from {entry['bin']} (cpu={cpu_bind}, mem={mem_bind}) ==="
            )
            future = executor.submit(run_single_checkpoint,
                                     bin_path=entry["bin"],
                                     workload_name=entry["name"],
                                     archive_id=None,
                                     interval=args.interval,
                                     copies=args.copies,
                                     resume_after=None,
                                     cpu_bind=cpu_bind,
                                     mem_bind=mem_bind)
            future_to_entry[future] = entry

        for future in concurrent.futures.as_completed(future_to_entry):
            entry = future_to_entry[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failures.append({"name": entry["name"], "error": str(exc)})

    if failures:
        print("Batch failures:")
        for failure in failures:
            print(f"- {failure['name']}: {failure['error']}")
        return 1

    print("Batch summary:")
    for result in results:
        print(
            f"- {result['name']}: archive={result['archive_id']}, checkpoints={result['checkpoint_count']}, dir={result['checkpoint_dir']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
