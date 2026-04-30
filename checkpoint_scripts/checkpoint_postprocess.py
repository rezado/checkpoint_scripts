import json
import os
import re
from itertools import product
from pathlib import Path


INSTRUCTION_REGEX = re.compile(r".*total guest instructions = (.*)\x1b.*")


def profiling_instrs(profiling_log, spec_app, using_new_script=False):
    new_path = os.path.join(profiling_log, spec_app, "profiling.out.log")
    old_path = os.path.join(profiling_log, f"{spec_app}-out.log")

    if using_new_script:
        path = new_path
        if not os.path.exists(new_path):
            raise FileNotFoundError(new_path)
    elif os.path.exists(old_path):
        path = old_path
    elif os.path.exists(new_path):
        path = new_path
    else:
        raise FileNotFoundError(f"missing profiling log: {old_path} or {new_path}")

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if "total guest instructions" not in line:
                continue
            match = INSTRUCTION_REGEX.findall(line)
            if not match:
                raise ValueError(f"failed to parse instructions from {path}")
            return match[0].replace(",", "")
    raise ValueError(f"failed to find instructions in {path}")


def cluster_weight(cluster_path, spec_app):
    points = {}
    weights = {}

    weights_path = Path(cluster_path) / spec_app / "weights0"
    simpoints_path = Path(cluster_path) / spec_app / "simpoints0"

    with weights_path.open("r", encoding="utf-8") as f:
        for line in f:
            weight, cluster_id = line.split()
            weights[cluster_id] = weight

    with simpoints_path.open("r", encoding="utf-8") as f:
        for line in f:
            point, cluster_id = line.split()
            if float(weights[cluster_id]) > 1e-4:
                points[point] = weights[cluster_id]

    return points


def per_checkpoint_generate_json(profiling_log, cluster_path, app_list, target_path):
    result = {}
    for spec in app_list:
        result[spec] = {
            "insts": profiling_instrs(profiling_log, spec),
            "points": cluster_weight(cluster_path, spec),
        }

    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=4) + "\n", encoding="utf-8")
    return result


def per_checkpoint_generate_worklist(cpt_path, target_path, json_result):
    checkpoint_root = Path(cpt_path)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", encoding="utf-8") as f:
        for workload_dir in sorted(entry for entry in checkpoint_root.iterdir() if entry.is_dir()):
            for checkpoint_dir in sorted(entry for entry in workload_dir.iterdir() if entry.is_dir()):
                workload = workload_dir.name
                point = checkpoint_dir.name
                if point not in json_result[workload]["points"]:
                    continue
                rel_path = checkpoint_dir.relative_to(checkpoint_root).as_posix()
                name = f"{workload}_{point}"
                print(f"{name} {rel_path} 0 0 20 20", file=f)


def generate_result_list(base_path, times, ids):
    result_list = []

    for profiling_id, cluster_id, checkpoint_id in product(
        range(ids[0], times[0]),
        range(ids[1], times[1]),
        range(ids[2], times[2]),
    ):
        cluster = f"cluster-{profiling_id}-{cluster_id}"
        profiling = f"profiling-{profiling_id}"
        checkpoint = f"checkpoint-{profiling_id}-{cluster_id}-{checkpoint_id}"
        result_list.append(
            {
                "cl_res": os.path.join(base_path, cluster),
                "profiling_log": os.path.join(base_path, "logs", profiling),
                "checkpoint_path": os.path.join(base_path, checkpoint),
                "json_path": os.path.join(base_path, checkpoint, f"{cluster}.json"),
                "list_path": os.path.join(base_path, checkpoint, "checkpoint.lst"),
            }
        )

    return result_list


def dump_result(base_path, spec_app_list, times, ids):
    result_list = generate_result_list(base_path, times, ids)

    for result in result_list:
        json_result = per_checkpoint_generate_json(
            result["profiling_log"],
            result["cl_res"],
            spec_app_list,
            result["json_path"],
        )
        per_checkpoint_generate_worklist(
            result["checkpoint_path"],
            result["list_path"],
            json_result,
        )


def generate_checkpoint_metadata(archive_root, workloads, times, ids):
    dump_result(
        base_path=archive_root,
        spec_app_list=sorted(set(workloads)),
        times=times,
        ids=ids,
    )
