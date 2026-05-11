import argparse
import concurrent.futures
import os
import shutil
from datetime import datetime
from pathlib import Path

from checkpoint_postprocess import cluster_weight
from checkpoint_postprocess import generate_checkpoint_metadata
from take_checkpoint import TakeCheckpointConfig
from take_checkpoint import generate_command
from take_checkpoint import level_first_exec

COMPRESSED_CHECKPOINT_SUFFIXES = (".gz", ".zstd")
AUTO_RESUME = "auto"
COMPLETE_STATE = "complete"
AUTO_RESUME_BACKUP_SUFFIX = "auto-resume-full"


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


def parse_simpoint_points(simpoints_path: str) -> list[str]:
    points = []
    with open(simpoints_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.split()
            if parts:
                points.append(parts[0])
    return points


def read_cluster_rows(cluster_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    simpoint_rows = {}
    weight_rows = {}
    simpoints_path = os.path.join(cluster_dir, "simpoints0")
    weights_path = os.path.join(cluster_dir, "weights0")

    with open(simpoints_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.split()
            if len(parts) >= 2:
                point, cluster_id = parts[0], parts[1]
                simpoint_rows[point] = cluster_id

    with open(weights_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.split()
            if len(parts) >= 2:
                weight, cluster_id = parts[0], parts[1]
                weight_rows[cluster_id] = weight

    return simpoint_rows, weight_rows


def checkpoint_point_has_artifact(point_dir: str) -> bool:
    if not os.path.isdir(point_dir):
        return False
    return any(name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES)
               for name in os.listdir(point_dir))


def detect_auto_resume_state(archive_root: str,
                             workload: str) -> dict[str, object]:
    profiling_path = os.path.join(archive_root, "profiling-0", workload,
                                  "simpoint_bbv.gz")
    cluster_dir = os.path.join(archive_root, "cluster-0-0", workload)
    simpoints_path = os.path.join(cluster_dir, "simpoints0")
    weights_path = os.path.join(cluster_dir, "weights0")
    simpoints_read_path = (f"{simpoints_path}.{AUTO_RESUME_BACKUP_SUFFIX}"
                           if os.path.exists(
                               f"{simpoints_path}.{AUTO_RESUME_BACKUP_SUFFIX}"
                           ) else simpoints_path)
    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0", workload)

    if not os.path.exists(profiling_path):
        return {
            "state": "fresh",
            "resume_after": None,
            "skip": False,
            "expected_points": [],
            "present_points": [],
            "missing_points": [],
        }

    if not (os.path.exists(simpoints_path) and os.path.exists(weights_path)):
        return {
            "state": "after_profiling",
            "resume_after": "profiling",
            "skip": False,
            "expected_points": [],
            "present_points": [],
            "missing_points": [],
        }

    expected_points = parse_simpoint_points(simpoints_read_path)
    present_points = []
    for point in expected_points:
        if checkpoint_point_has_artifact(os.path.join(checkpoint_dir, point)):
            present_points.append(point)
    missing_points = [
        point for point in expected_points if point not in set(present_points)
    ]

    if expected_points and not missing_points:
        return {
            "state": COMPLETE_STATE,
            "resume_after": None,
            "skip": True,
            "expected_points": expected_points,
            "present_points": present_points,
            "missing_points": [],
        }

    return {
        "state": "after_cluster",
        "resume_after": "cluster",
        "skip": False,
        "expected_points": expected_points,
        "present_points": present_points,
        "missing_points": missing_points,
    }


def backup_file_once(path: str, suffix: str) -> None:
    if not os.path.exists(path):
        return
    backup_path = f"{path}.{suffix}"
    if not os.path.exists(backup_path):
        shutil.copy2(path, backup_path)


def restore_auto_resume_artifacts(archive_root: str, workload: str) -> None:
    cluster_dir = os.path.join(archive_root, "cluster-0-0", workload)
    for name in ["simpoints0", "weights0"]:
        path = os.path.join(cluster_dir, name)
        backup_path = f"{path}.{AUTO_RESUME_BACKUP_SUFFIX}"
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, path)


def prepare_auto_resume_artifacts(archive_root: str, workload: str,
                                  state: dict[str, object]) -> str | None:
    resume_after = state["resume_after"]
    if resume_after != "cluster":
        return resume_after

    missing_points = list(state.get("missing_points", []))
    present_points = list(state.get("present_points", []))
    if not missing_points or not present_points:
        return resume_after

    cluster_dir = os.path.join(archive_root, "cluster-0-0", workload)
    simpoints_path = os.path.join(cluster_dir, "simpoints0")
    weights_path = os.path.join(cluster_dir, "weights0")
    restore_auto_resume_artifacts(archive_root, workload)
    backup_file_once(simpoints_path, AUTO_RESUME_BACKUP_SUFFIX)
    backup_file_once(weights_path, AUTO_RESUME_BACKUP_SUFFIX)

    simpoint_rows, weight_rows = read_cluster_rows(cluster_dir)
    with open(simpoints_path, "w", encoding="utf-8") as simpoints, open(
            weights_path, "w", encoding="utf-8") as weights:
        for new_cluster_id, point in enumerate(missing_points):
            old_cluster_id = simpoint_rows[point]
            print(f"{point} {new_cluster_id}", file=simpoints)
            print(f"{weight_rows[old_cluster_id]} {new_cluster_id}",
                  file=weights)

    return resume_after


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
                        choices=["profiling", "cluster", AUTO_RESUME],
                        help="Resume from a later stage")
    parser.add_argument(
        "--allow-new-archives",
        action="store_true",
        help="Allow --bin-list --resume-after auto to create archives for bins without a previous archive",
    )
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
        if args.resume_after not in (None, AUTO_RESUME):
            raise ValueError(
                "--resume-after with --bin-list only supports auto"
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
                        resume_after: str | None,
                        preserve_checkpoint_workload: bool = False) -> None:
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
            os.path.join(archive_root, "logs", "checkpoint-0-0-0", workload),
            os.path.join(archive_root, "checkpoint-0-0-0", "cluster-0-0.json"),
            os.path.join(archive_root, "checkpoint-0-0-0", "checkpoint.lst"),
        ],
    }
    if not preserve_checkpoint_workload:
        stage_paths["checkpoint"].insert(
            0, os.path.join(archive_root, "checkpoint-0-0-0", workload))

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


def find_latest_archive_for_workload(archive_parent: str,
                                     workload_name: str) -> str | None:
    archive_root = Path(archive_parent)
    if not archive_root.is_dir():
        return None

    prefix = f"single_bin_nemu_{workload_name}_"
    matches = [
        path for path in archive_root.iterdir()
        if path.is_dir() and path.name.startswith(prefix)
    ]
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name)).name


def plan_batch_auto_resume(
        entries: list[dict[str, str]], *,
        archive_parent: str = "archive",
        allow_new_archives: bool = False
) -> tuple[list[dict[str, str | None]], list[dict[str, str | bool]]]:
    planned = []
    skipped = []

    for entry in entries:
        archive_id = find_latest_archive_for_workload(archive_parent,
                                                      entry["name"])
        if archive_id is None:
            if not allow_new_archives:
                raise FileNotFoundError(
                    f"no previous archive found for workload: {entry['name']}")
            planned.append({
                **entry,
                "archive_id": None,
                "resume_after": None,
            })
            continue

        archive_root = os.path.join(archive_parent, archive_id)
        state = detect_auto_resume_state(archive_root, entry["name"])
        if state["skip"]:
            skipped.append({
                **entry,
                "archive_id": archive_id,
                "state": str(state["state"]),
                "skipped": True,
            })
            continue

        planned.append({
            **entry,
            "archive_id": archive_id,
            "resume_after": state["resume_after"],
            "state": str(state["state"]),
        })

    return planned, skipped


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

    effective_resume_after = resume_after
    preserve_checkpoint_workload = False
    if resume_after == AUTO_RESUME:
        state = detect_auto_resume_state(archive_root, workload_name)
        if state["skip"]:
            checkpoint_count = count_checkpoints(archive_root, workload_name)
            checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0",
                                          workload_name)
            print(f"Archive: {resolved_archive_id}")
            print(f"Resume after: auto ({state['state']})")
            print(f"Skipping completed workload: {workload_name}")
            print(f"Checkpoint count: {checkpoint_count}")
            print(f"Checkpoint dir: {checkpoint_dir}")
            return {
                "name": workload_name,
                "archive_id": resolved_archive_id,
                "archive_root": archive_root,
                "checkpoint_count": checkpoint_count,
                "checkpoint_dir": checkpoint_dir,
                "skipped": 1,
            }
        effective_resume_after = prepare_auto_resume_artifacts(
            archive_root, workload_name, state)
        preserve_checkpoint_workload = bool(state.get("present_points"))

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

    reset_stage_outputs(
        archive_root,
        workload_name,
        effective_resume_after,
        preserve_checkpoint_workload=preserve_checkpoint_workload,
    )
    validate_resume_artifacts(archive_root, workload_name, effective_resume_after)
    ensure_resume_logs(archive_root, workload_name, effective_resume_after)

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
                            resume_after=effective_resume_after,
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
    print(f"Resume after: {effective_resume_after or 'fresh'}")

    try:
        level_first_exec(root)
    finally:
        if resume_after == AUTO_RESUME:
            restore_auto_resume_artifacts(archive_root, workload_name)
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
    planned_entries = []
    skipped_entries = []
    if args.resume_after == AUTO_RESUME:
        planned_entries, skipped_entries = plan_batch_auto_resume(
            entries,
            archive_parent="archive",
            allow_new_archives=args.allow_new_archives,
        )
    else:
        planned_entries = [{
            **entry,
            "archive_id": None,
            "resume_after": None,
        } for entry in entries]

    for entry in planned_entries:
        validate_input_args(
            build_single_run_args(bin_path=entry["bin"],
                                  workload_name=entry["name"],
                                  archive_id=entry["archive_id"],
                                  interval=args.interval,
                                  copies=args.copies,
                                  max_workers=args.max_workers,
                                  resume_after=entry["resume_after"]))

    print(f"Batch size: {len(entries)}")
    if args.resume_after == AUTO_RESUME:
        print(f"Auto resume planned: {len(planned_entries)}")
        print(f"Auto resume skipped: {len(skipped_entries)}")
    print(f"Max workers: {args.max_workers}")
    results = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.max_workers) as executor:
        future_to_entry = {}
        for index, entry in enumerate(planned_entries):
            cpu_bind, mem_bind = get_worker_bindings(index)
            print(
                f"=== [{index + 1}/{len(entries)}] Checkpointing {entry['name']} from {entry['bin']} (cpu={cpu_bind}, mem={mem_bind}) ==="
            )
            future = executor.submit(run_single_checkpoint,
                                     bin_path=entry["bin"],
                                     workload_name=entry["name"],
                                     archive_id=entry["archive_id"],
                                     interval=args.interval,
                                     copies=args.copies,
                                     resume_after=entry["resume_after"],
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
    for skipped in skipped_entries:
        print(f"- {skipped['name']}: archive={skipped['archive_id']}, skipped=complete")
    for result in results:
        print(
            f"- {result['name']}: archive={result['archive_id']}, checkpoints={result['checkpoint_count']}, dir={result['checkpoint_dir']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
