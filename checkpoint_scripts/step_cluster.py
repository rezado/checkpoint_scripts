import argparse
import os
import random
import subprocess

from checkpoint_env import load_nemu_paths
from checkpoint_layout import cluster_dir
from checkpoint_layout import cluster_log_dir
from checkpoint_layout import profiling_dir


def max_k_for_workload(workload: str) -> int:
    if workload == "xalancbmk":
        return 100
    return 30


def build_cluster_command(*,
                          simpoint_bin: str,
                          archive_root: str,
                          workload: str,
                          cpu_bind: str,
                          mem_bind: str,
                          seedkm: int,
                          seedproj: int) -> list[str]:
    output_dir = cluster_dir(archive_root, workload)
    return [
        "numactl",
        f"--cpunodebind={cpu_bind}",
        f"--membind={mem_bind}",
        simpoint_bin,
        "-loadFVFile",
        os.path.join(profiling_dir(archive_root, workload), "simpoint_bbv.gz"),
        "-saveSimpoints",
        os.path.join(output_dir, "simpoints0"),
        "-saveSimpointWeights",
        os.path.join(output_dir, "weights0"),
        "-inputVectorsGzipped",
        "-maxK",
        str(max_k_for_workload(workload)),
        "-numInitSeeds",
        "2",
        "-iters",
        "1000",
        "-seedkm",
        str(seedkm),
        "-seedproj",
        str(seedproj),
    ]


def run_cluster_step(*,
                     archive_root: str,
                     workload: str,
                     cpu_bind: str = "0",
                     mem_bind: str = "0") -> None:
    nemu_paths = load_nemu_paths()
    output_dir = cluster_dir(archive_root, workload)
    os.makedirs(output_dir, exist_ok=True)
    log_dir = cluster_log_dir(archive_root, workload)
    os.makedirs(log_dir, exist_ok=True)
    command = build_cluster_command(
        simpoint_bin=nemu_paths.simpoint,
        archive_root=archive_root,
        workload=workload,
        cpu_bind=cpu_bind,
        mem_bind=mem_bind,
        seedkm=random.randint(100000, 999999),
        seedproj=random.randint(100000, 999999),
    )

    with open(os.path.join(log_dir, "cluster.out.log"), "w",
              encoding="utf-8") as out, open(
                  os.path.join(log_dir, "cluster.err.log"), "w",
                  encoding="utf-8") as err:
        subprocess.run(command, stdout=out, stderr=err, check=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the clustering step")
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--workload", required=True)
    parser.add_argument("--cpu-bind", default="0")
    parser.add_argument("--mem-bind", default="0")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    run_cluster_step(
        archive_root=args.archive_root,
        workload=args.workload,
        cpu_bind=args.cpu_bind,
        mem_bind=args.mem_bind,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
