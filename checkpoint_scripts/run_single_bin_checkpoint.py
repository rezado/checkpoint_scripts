import argparse
import concurrent.futures
import os
import shutil
from datetime import datetime
from pathlib import Path

from checkpoint_layout import checkpoint_stage_name
from checkpoint_layout import cluster_stage_name
from checkpoint_layout import profiling_stage_name
from checkpoint_postprocess import cluster_weight
from checkpoint_postprocess import generate_checkpoint_metadata
from take_checkpoint import TakeCheckpointConfig
from take_checkpoint import generate_command
from take_checkpoint import level_first_exec

COMPRESSED_CHECKPOINT_SUFFIXES = (".gz", ".zstd")
AUTO_RESUME = "auto"
COMPLETE_STATE = "complete"
AUTO_RESUME_BACKUP_SUFFIX = "auto-resume-full"
KNOWN_BIN_SUFFIXES = (
    ".fw_payload.bin",
    ".payload.bin",
    ".gcpt.bin",
    ".gcpt",
    ".bin",
)


def build_archive_layout(archive_root: str) -> dict[str, str]:
    return {
        "buffer_path": archive_root,
        "gcpt_bins": os.path.join(archive_root, "gcpt_bins"),
        "logs": os.path.join(archive_root, "logs"),
        "metadata": os.path.join(archive_root, "metadata"),
        "json": os.path.join(archive_root, "json"),
    }


def ensure_directories(paths) -> None:
    for path in paths:
        os.makedirs(path, exist_ok=True)


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)


def generate_archive_id(mode: str, workload: str | None = None) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    if mode == "file":
        return f"single_bin_nemu_{safe_name(workload or 'workload')}_{timestamp}"
    return f"multi_bin_nemu_{timestamp}"


def stage_names() -> dict[str, str]:
    return {
        "profiling": profiling_stage_name(),
        "cluster": cluster_stage_name(),
        "checkpoint": checkpoint_stage_name(),
    }


def profiling_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, stage_names()["profiling"], workload)


def cluster_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, stage_names()["cluster"], workload)


def checkpoint_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, stage_names()["checkpoint"], workload)


def profiling_log_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, "logs", stage_names()["profiling"], workload)


def cluster_log_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, "logs", stage_names()["cluster"], workload)


def checkpoint_log_dir(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, "logs", stage_names()["checkpoint"], workload)


def workload_json_path(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, "json", f"{workload}.json")


def checkpoint_list_path(archive_root: str) -> str:
    return os.path.join(archive_root, stage_names()["checkpoint"], "checkpoint.lst")


def write_request_metadata(metadata_dir: str,
                           request: dict,
                           filename: str = "single_bin_request.yaml") -> str:
    os.makedirs(metadata_dir, exist_ok=True)
    output_path = os.path.join(metadata_dir, filename)
    lines = []
    for key, value in request.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(item) for item in value) + "]"
        else:
            rendered = value
        lines.append(f"{key}: {rendered}")
    lines.append(f"timestamp: {datetime.now().isoformat(timespec='seconds')}")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(str(line) for line in lines) + "\n")
    return output_path


def clear_aggregate_metadata(archive_root: str) -> None:
    for path in [
            os.path.join(archive_root, "json", "checkpoints_cov0.3.json"),
            os.path.join(archive_root, "json", "checkpoints_all.json"),
            checkpoint_list_path(archive_root),
            os.path.join(archive_root, "checkpoint-0-0-0", "checkpoint.lst"),
            os.path.join(archive_root, "checkpoint-0-0-0", "cluster-0-0.json"),
    ]:
        remove_path(path)


def validate_resume_artifacts(archive_root: str, workload: str,
                              resume_after: str | None) -> None:
    required = []
    if resume_after == "profiling":
        required = [os.path.join(profiling_dir(archive_root, workload), "simpoint_bbv.gz")]
    elif resume_after == "cluster":
        required = [
            os.path.join(cluster_dir(archive_root, workload), "simpoints0"),
            os.path.join(cluster_dir(archive_root, workload), "weights0"),
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


def read_cluster_rows(cluster_output_dir: str) -> tuple[dict[str, str], dict[str, str]]:
    simpoint_rows = {}
    weight_rows = {}
    simpoints_path = os.path.join(cluster_output_dir, "simpoints0")
    weights_path = os.path.join(cluster_output_dir, "weights0")

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


def detect_auto_resume_state(archive_root: str, workload: str) -> dict[str, object]:
    profiling_path = os.path.join(profiling_dir(archive_root, workload), "simpoint_bbv.gz")
    workload_cluster_dir = cluster_dir(archive_root, workload)
    simpoints_path = os.path.join(workload_cluster_dir, "simpoints0")
    weights_path = os.path.join(workload_cluster_dir, "weights0")
    simpoints_read_path = (f"{simpoints_path}.{AUTO_RESUME_BACKUP_SUFFIX}"
                           if os.path.exists(
                               f"{simpoints_path}.{AUTO_RESUME_BACKUP_SUFFIX}")
                           else simpoints_path)
    workload_checkpoint_dir = checkpoint_dir(archive_root, workload)

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
        if checkpoint_point_has_artifact(os.path.join(workload_checkpoint_dir, point)):
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
    workload_cluster_dir = cluster_dir(archive_root, workload)
    for name in ["simpoints0", "weights0"]:
        path = os.path.join(workload_cluster_dir, name)
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

    workload_cluster_dir = cluster_dir(archive_root, workload)
    simpoints_path = os.path.join(workload_cluster_dir, "simpoints0")
    weights_path = os.path.join(workload_cluster_dir, "weights0")
    restore_auto_resume_artifacts(archive_root, workload)
    backup_file_once(simpoints_path, AUTO_RESUME_BACKUP_SUFFIX)
    backup_file_once(weights_path, AUTO_RESUME_BACKUP_SUFFIX)

    simpoint_rows, weight_rows = read_cluster_rows(workload_cluster_dir)
    with open(simpoints_path, "w", encoding="utf-8") as simpoints, open(
            weights_path, "w", encoding="utf-8") as weights:
        for new_cluster_id, point in enumerate(missing_points):
            old_cluster_id = simpoint_rows[point]
            print(f"{point} {new_cluster_id}", file=simpoints)
            print(f"{weight_rows[old_cluster_id]} {new_cluster_id}", file=weights)

    return resume_after


def validate_outputs(archive_root: str, workload: str) -> None:
    required = [
        os.path.join(profiling_dir(archive_root, workload), "simpoint_bbv.gz"),
        os.path.join(cluster_dir(archive_root, workload), "simpoints0"),
        os.path.join(cluster_dir(archive_root, workload), "weights0"),
    ]
    for path in required:
        if not os.path.exists(path):
            raise FileNotFoundError(f"expected output missing: {path}")

    workload_checkpoint_dir = checkpoint_dir(archive_root, workload)
    if not os.path.isdir(workload_checkpoint_dir):
        raise FileNotFoundError(
            f"expected checkpoint output directory missing: {workload_checkpoint_dir}")

    checkpoint_count = sum(
        1 for root, _, files in os.walk(workload_checkpoint_dir)
        for name in files if name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES))
    if checkpoint_count == 0:
        raise FileNotFoundError(
            f"no compressed checkpoint artifacts found under: {workload_checkpoint_dir}")

    expected_points = cluster_weight(
        os.path.join(archive_root, stage_names()["cluster"]), workload)
    missing_points = []
    for point in sorted(expected_points):
        point_dir = os.path.join(workload_checkpoint_dir, point)
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
        "Run profiling, cluster, and checkpoint from one bin or a directory of bins with NEMU",
    )
    parser.add_argument("--input-path",
                        required=True,
                        help="Path to a GCPT-bootable bin file or a directory of bin files")
    parser.add_argument("--name",
                        help="Optional workload name override used only with a single input file")
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
                        help="Maximum parallel workloads used in directory mode")
    parser.add_argument("--resume-after",
                        choices=["profiling", "cluster", AUTO_RESUME],
                        help="Resume from a later stage")
    return parser


def inspect_input_kind(input_path: str) -> str:
    if os.path.isfile(input_path):
        return "file"
    if os.path.isdir(input_path):
        return "directory"
    raise FileNotFoundError(f"input path does not exist: {input_path}")


def validate_input_args(args) -> None:
    if not os.path.exists(args.input_path):
        raise FileNotFoundError(f"input path does not exist: {args.input_path}")
    if not os.access(args.input_path, os.R_OK):
        raise PermissionError(f"input path is not readable: {args.input_path}")

    input_kind = inspect_input_kind(args.input_path)
    if input_kind == "directory" and args.name is not None:
        raise ValueError("--name can only be used with a single file input")

    if args.resume_after is not None and args.archive_id is None:
        raise ValueError("--archive-id is required when using --resume-after")

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
    log_dir = profiling_log_dir(archive_root, workload)
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
            profiling_dir(archive_root, workload),
            profiling_log_dir(archive_root, workload),
        ],
        "cluster": [
            cluster_dir(archive_root, workload),
            cluster_log_dir(archive_root, workload),
        ],
        "checkpoint": [
            checkpoint_log_dir(archive_root, workload),
            workload_json_path(archive_root, workload),
            os.path.join(archive_root, "checkpoint-0-0-0", "cluster-0-0.json"),
            os.path.join(archive_root, "checkpoint-0-0-0", "checkpoint.lst"),
        ],
    }
    if not preserve_checkpoint_workload:
        stage_paths["checkpoint"].insert(0, checkpoint_dir(archive_root, workload))

    for stage in stages_to_remove:
        for path in stage_paths[stage]:
            remove_path(path)


def count_checkpoints(archive_root: str, workload: str) -> int:
    workload_checkpoint_dir = checkpoint_dir(archive_root, workload)
    return sum(
        1 for root, _, files in os.walk(workload_checkpoint_dir)
        for name in files if name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES))


def build_single_run_args(input_path: str, workload_name: str | None,
                          archive_id: str | None, interval: int, copies: int,
                          max_workers: int, resume_after: str | None) -> argparse.Namespace:
    return argparse.Namespace(
        input_path=input_path,
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


def strip_known_bin_suffix(file_name: str) -> str:
    for suffix in KNOWN_BIN_SUFFIXES:
        if file_name.endswith(suffix) and len(file_name) > len(suffix):
            return file_name[:-len(suffix)]
    return Path(file_name).stem


def longest_common_suffix(names: list[str]) -> str:
    if not names:
        return ""
    reversed_names = [name[::-1] for name in names]
    return os.path.commonprefix(reversed_names)[::-1]


def derive_common_bin_suffix(names: list[str]) -> str:
    for suffix in KNOWN_BIN_SUFFIXES:
        if all(name.endswith(suffix) for name in names):
            return suffix

    common_suffix = longest_common_suffix(names)
    if not common_suffix:
        return ""

    for marker in [".", "_", "-"]:
        index = common_suffix.find(marker)
        if index > 0:
            return common_suffix[index:]
    return common_suffix


def derive_directory_entries(input_dir: str) -> tuple[list[dict[str, str]], str]:
    files = sorted(
        entry for entry in Path(input_dir).iterdir() if entry.is_file())
    if not files:
        raise ValueError(f"input directory does not contain any files: {input_dir}")

    basenames = [entry.name for entry in files]
    common_suffix = derive_common_bin_suffix(basenames)
    entries = []
    seen_names = set()

    for file_path in files:
        workload_name = file_path.name
        if common_suffix and len(workload_name) > len(common_suffix):
            workload_name = workload_name[:-len(common_suffix)]
        workload_name = workload_name.rstrip(".-_") or strip_known_bin_suffix(
            file_path.name)
        if not workload_name:
            raise ValueError(
                f"unable to derive workload name from file: {file_path}")
        if workload_name in seen_names:
            raise ValueError(
                f"duplicate workload name derived from input directory: {workload_name}")

        entries.append({"bin": str(file_path), "name": workload_name})
        seen_names.add(workload_name)

    return entries, common_suffix


def load_input_entries(input_path: str,
                       name_override: str | None = None
                       ) -> tuple[str, list[dict[str, str]], str | None]:
    input_kind = inspect_input_kind(input_path)
    if input_kind == "file":
        workload_name = name_override or strip_known_bin_suffix(
            os.path.basename(os.path.normpath(input_path)))
        return "file", [{"bin": input_path, "name": workload_name}], None
    entries, common_suffix = derive_directory_entries(input_path)
    return "directory", entries, common_suffix


def run_single_checkpoint(*, bin_path: str, workload_name: str, archive_root: str,
                          interval: int, copies: int, resume_after: str | None,
                          cpu_bind: str = "0", mem_bind: str = "0",
                          metadata_dir: str | None = None,
                          generate_metadata: bool = True) -> dict[str, str | int]:
    layout = build_archive_layout(archive_root)
    ensure_directories(layout.values())

    effective_resume_after = resume_after
    preserve_checkpoint_workload = False
    if resume_after == AUTO_RESUME:
        state = detect_auto_resume_state(archive_root, workload_name)
        if state["skip"]:
            checkpoint_count = count_checkpoints(archive_root, workload_name)
            workload_checkpoint_dir = checkpoint_dir(archive_root, workload_name)
            print(f"Archive: {os.path.basename(archive_root)}")
            print(f"Resume after: auto ({state['state']})")
            print(f"Skipping completed workload: {workload_name}")
            print(f"Checkpoint count: {checkpoint_count}")
            print(f"Checkpoint dir: {workload_checkpoint_dir}")
            return {
                "name": workload_name,
                "archive_id": os.path.basename(archive_root),
                "archive_root": archive_root,
                "checkpoint_count": checkpoint_count,
                "checkpoint_dir": workload_checkpoint_dir,
                "skipped": 1,
            }
        effective_resume_after = prepare_auto_resume_artifacts(
            archive_root, workload_name, state)
        preserve_checkpoint_workload = bool(state.get("present_points"))

    request = {
        "bin": os.path.realpath(bin_path),
        "name": workload_name,
        "archive_id": os.path.basename(archive_root),
        "interval": interval,
        "copies": copies,
        "resume_after": resume_after,
    }
    request_dir = metadata_dir or layout["metadata"]
    metadata_path = write_request_metadata(request_dir,
                                           request,
                                           filename=f"{workload_name}.yaml")
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

    print(f"Archive: {os.path.basename(archive_root)}")
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
    if generate_metadata:
        clear_aggregate_metadata(archive_root)
        generate_checkpoint_metadata(
            archive_root=archive_root,
            workloads=[workload_name],
            times=[1, 1, 1],
            ids=[0, 0, 0],
        )

    checkpoint_count = count_checkpoints(archive_root, workload_name)
    workload_checkpoint_dir = checkpoint_dir(archive_root, workload_name)
    print(f"Checkpoint count: {checkpoint_count}")
    print(f"Checkpoint dir: {workload_checkpoint_dir}")

    return {
        "name": workload_name,
        "archive_id": os.path.basename(archive_root),
        "archive_root": archive_root,
        "checkpoint_count": checkpoint_count,
        "checkpoint_dir": workload_checkpoint_dir,
    }


def main() -> int:
    args = build_arg_parser().parse_args()
    validate_input_args(args)

    input_mode, entries, common_suffix = load_input_entries(args.input_path,
                                                            args.name)

    for entry in entries:
        validate_input_args(
            build_single_run_args(input_path=entry["bin"],
                                  workload_name=entry["name"],
                                  archive_id=args.archive_id,
                                  interval=args.interval,
                                  copies=args.copies,
                                  max_workers=args.max_workers,
                                  resume_after=args.resume_after))

    if input_mode == "file":
        archive_id = args.archive_id or generate_archive_id("file", entries[0]["name"])
        archive_root = os.path.realpath(os.path.join("archive", archive_id))
        ensure_directories(build_archive_layout(archive_root).values())
        clear_aggregate_metadata(archive_root)
        write_request_metadata(
            os.path.join(archive_root, "metadata"),
            {
                "mode": "single",
                "input_path": os.path.realpath(args.input_path),
                "name": entries[0]["name"],
                "archive_id": archive_id,
                "interval": args.interval,
                "copies": args.copies,
                "resume_after": args.resume_after,
            },
        )
        run_single_checkpoint(bin_path=entries[0]["bin"],
                              workload_name=entries[0]["name"],
                              archive_root=archive_root,
                              interval=args.interval,
                              copies=args.copies,
                              resume_after=args.resume_after)
        return 0

    archive_id = args.archive_id or generate_archive_id("directory")
    archive_root = os.path.realpath(os.path.join("archive", archive_id))
    layout = build_archive_layout(archive_root)
    ensure_directories(layout.values())
    clear_aggregate_metadata(archive_root)
    write_request_metadata(
        layout["metadata"],
        {
            "mode": "directory",
            "input_path": os.path.realpath(args.input_path),
            "archive_id": archive_id,
            "interval": args.interval,
            "copies": args.copies,
            "resume_after": args.resume_after,
            "max_workers": args.max_workers,
            "common_suffix": common_suffix or "",
            "workloads": [entry["name"] for entry in entries],
        },
        filename="batch_request.yaml",
    )

    print(f"Batch size: {len(entries)}")
    print(f"Archive: {archive_id}")
    print(f"Max workers: {args.max_workers}")
    if common_suffix:
        print(f"Derived common suffix: {common_suffix}")

    results = []
    failures = []
    requests_dir = os.path.join(layout["metadata"], "requests")
    os.makedirs(requests_dir, exist_ok=True)
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
                                     archive_root=archive_root,
                                     interval=args.interval,
                                     copies=args.copies,
                                     resume_after=args.resume_after,
                                     cpu_bind=cpu_bind,
                                     mem_bind=mem_bind,
                                     metadata_dir=requests_dir,
                                     generate_metadata=False)
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

    generate_checkpoint_metadata(
        archive_root=archive_root,
        workloads=[entry["name"] for entry in entries],
        times=[1, 1, 1],
        ids=[0, 0, 0],
    )

    print("Batch summary:")
    for result in results:
        suffix = ", skipped=complete" if result.get("skipped") else ""
        print(
            f"- {result['name']}: archive={result['archive_id']}, checkpoints={result['checkpoint_count']}, dir={result['checkpoint_dir']}{suffix}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
