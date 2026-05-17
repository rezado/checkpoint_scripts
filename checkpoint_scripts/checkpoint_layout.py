import os


def _normalize_ids(ids):
    return tuple(int(item) for item in ids)


def format_stage_name(base: str, *ids) -> str:
    normalized = _normalize_ids(ids)
    if not normalized or all(item == 0 for item in normalized):
        return base
    return f"{base}-{'-'.join(str(item) for item in normalized)}"


def profiling_stage_name(profiling_id=0) -> str:
    return format_stage_name("profiling", profiling_id)


def cluster_stage_name(profiling_id=0, cluster_id=0) -> str:
    return format_stage_name("cluster", profiling_id, cluster_id)


def checkpoint_stage_name(profiling_id=0, cluster_id=0, checkpoint_id=0) -> str:
    return format_stage_name("checkpoint", profiling_id, cluster_id,
                             checkpoint_id)


def archive_layout(archive_root: str) -> dict[str, str]:
    return {
        "buffer_path": archive_root,
        "gcpt_bins": os.path.join(archive_root, "gcpt_bins"),
        "logs": os.path.join(archive_root, "logs"),
        "metadata": os.path.join(archive_root, "metadata"),
        "json": os.path.join(archive_root, "json"),
    }


def profiling_dir(archive_root: str, workload: str, profiling_id=0) -> str:
    return os.path.join(archive_root, profiling_stage_name(profiling_id),
                        workload)


def cluster_dir(archive_root: str,
                workload: str,
                profiling_id=0,
                cluster_id=0) -> str:
    return os.path.join(archive_root,
                        cluster_stage_name(profiling_id, cluster_id), workload)


def checkpoint_dir(archive_root: str,
                   workload: str,
                   profiling_id=0,
                   cluster_id=0,
                   checkpoint_id=0) -> str:
    return os.path.join(
        archive_root,
        checkpoint_stage_name(profiling_id, cluster_id, checkpoint_id),
        workload,
    )


def profiling_log_dir(archive_root: str, workload: str, profiling_id=0) -> str:
    return os.path.join(archive_root, "logs", profiling_stage_name(profiling_id),
                        workload)


def cluster_log_dir(archive_root: str,
                    workload: str,
                    profiling_id=0,
                    cluster_id=0) -> str:
    return os.path.join(
        archive_root,
        "logs",
        cluster_stage_name(profiling_id, cluster_id),
        workload,
    )


def checkpoint_log_dir(archive_root: str,
                       workload: str,
                       profiling_id=0,
                       cluster_id=0,
                       checkpoint_id=0) -> str:
    return os.path.join(
        archive_root,
        "logs",
        checkpoint_stage_name(profiling_id, cluster_id, checkpoint_id),
        workload,
    )


def workload_json_path(archive_root: str, workload: str) -> str:
    return os.path.join(archive_root, "json", f"{workload}.json")


def checkpoint_list_path(archive_root: str,
                         profiling_id=0,
                         cluster_id=0,
                         checkpoint_id=0) -> str:
    return os.path.join(
        archive_root,
        checkpoint_stage_name(profiling_id, cluster_id, checkpoint_id),
        "checkpoint.lst",
    )


def json_output_dir(base_path: str, checkpoint_name: str) -> str:
    if checkpoint_name == "checkpoint":
        return os.path.join(base_path, "json")
    return os.path.join(base_path, "json", checkpoint_name)
