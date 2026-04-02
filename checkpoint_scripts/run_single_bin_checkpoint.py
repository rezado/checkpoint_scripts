import argparse
import os
import shutil
from datetime import datetime

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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=
        "Run profiling, cluster, and checkpoint from a single GCPT bin with NEMU"
    )
    parser.add_argument("--bin",
                        required=True,
                        help="Path to a GCPT-bootable bin file")
    parser.add_argument("--name", required=True, help="Workload name")
    parser.add_argument("--archive-id", help="Existing or new archive id")
    parser.add_argument("--interval",
                        type=int,
                        default=20_000_000,
                        help="Checkpoint interval")
    parser.add_argument("--copies",
                        type=int,
                        default=1,
                        help="Core count passed to the checkpoint flow")
    parser.add_argument("--resume-after",
                        choices=["profiling", "cluster"],
                        help="Resume from a later stage")
    return parser


def validate_input_args(args) -> None:
    if not os.path.isfile(args.bin):
        raise FileNotFoundError(f"input bin does not exist: {args.bin}")
    if not os.access(args.bin, os.R_OK):
        raise PermissionError(f"input bin is not readable: {args.bin}")
    if not args.name.strip():
        raise ValueError("workload name must not be empty")
    if args.copies < 1:
        raise ValueError("--copies must be at least 1")
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


def count_checkpoints(archive_root: str, workload: str) -> int:
    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0", workload)
    return sum(
        1 for root, _, files in os.walk(checkpoint_dir)
        for name in files if name.endswith(COMPRESSED_CHECKPOINT_SUFFIXES))


def main() -> int:
    args = build_arg_parser().parse_args()
    validate_input_args(args)

    archive_id = args.archive_id or generate_archive_id(args.name)
    archive_root = os.path.realpath(os.path.join("archive", archive_id))
    layout = build_archive_layout(archive_root)
    ensure_directories(layout.values())

    request = {
        "bin": os.path.realpath(args.bin),
        "name": args.name,
        "archive_id": archive_id,
        "interval": args.interval,
        "copies": args.copies,
        "resume_after": args.resume_after,
    }
    metadata_path = write_request_metadata(layout["metadata"], request)
    copied_bin = copy_input_bin(args.bin, os.path.join(layout["gcpt_bins"],
                                                       args.name))

    validate_resume_artifacts(archive_root, args.name, args.resume_after)
    ensure_resume_logs(archive_root, args.name, args.resume_after)

    nemu_home = os.environ.get("NEMU_HOME")
    if not nemu_home:
        raise EnvironmentError("NEMU_HOME is not set")
    validate_runtime_tools(nemu_home)

    take_config = TakeCheckpointConfig(start_id="0,0,0",
                                       times="1,1,1",
                                       path_env_vars_to_check=["NEMU_HOME"])
    config = take_config.get_config()
    config["utils"]["interval"] = str(args.interval)

    root = generate_command(workload_folder=layout["gcpt_bins"],
                            workload=args.name,
                            buffer=archive_root,
                            bin_suffix="",
                            emu="NEMU",
                            log_folder=layout["logs"],
                            cpu_bind="0",
                            mem_bind="0",
                            copies=str(args.copies),
                            config=config,
                            resume_after=args.resume_after,
                            all_in_one_workload=True)
    if root is None:
        raise RuntimeError("failed to generate execution tree")

    print(f"Archive: {archive_id}")
    print(f"Input bin copied to: {copied_bin}")
    print(f"Metadata: {metadata_path}")
    print(f"Interval: {args.interval}")
    print(f"Copies: {args.copies}")
    print(f"Resume after: {args.resume_after or 'fresh'}")

    level_first_exec(root)
    validate_outputs(archive_root, args.name)

    checkpoint_count = count_checkpoints(archive_root, args.name)
    checkpoint_dir = os.path.join(archive_root, "checkpoint-0-0-0", args.name)
    print(f"Checkpoint count: {checkpoint_count}")
    print(f"Checkpoint dir: {checkpoint_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
