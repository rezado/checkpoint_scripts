def _normalize_ids(ids):
    return tuple(int(item) for item in ids)


def format_stage_name(base: str, *ids) -> str:
    normalized = _normalize_ids(ids)
    if normalized and all(item == 0 for item in normalized):
        return base
    if not normalized:
        return base
    return f"{base}-{'-'.join(str(item) for item in normalized)}"


def profiling_stage_name(profiling_id=0) -> str:
    return format_stage_name("profiling", profiling_id)


def cluster_stage_name(profiling_id=0, cluster_id=0) -> str:
    return format_stage_name("cluster", profiling_id, cluster_id)


def checkpoint_stage_name(profiling_id=0, cluster_id=0, checkpoint_id=0) -> str:
    return format_stage_name("checkpoint", profiling_id, cluster_id, checkpoint_id)


def json_output_dir(base_path: str, checkpoint_name: str) -> str:
    if checkpoint_name == "checkpoint":
        return f"{base_path}/json"
    return f"{base_path}/json/{checkpoint_name}"
