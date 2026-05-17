import os
from dataclasses import dataclass


@dataclass(frozen=True)
class NemuPaths:
    home: str
    nemu: str
    simpoint: str


def require_env_path(env_var: str) -> str:
    value = os.environ.get(env_var)
    if not value:
        raise EnvironmentError(f"{env_var} is not set")
    if not os.path.isdir(value):
        raise EnvironmentError(f"{env_var} does not point to a directory: {value}")
    return value


def load_nemu_paths() -> NemuPaths:
    nemu_home = require_env_path("NEMU_HOME")
    paths = NemuPaths(
        home=nemu_home,
        nemu=os.path.join(nemu_home, "build", "riscv64-nemu-interpreter"),
        simpoint=os.path.join(
            nemu_home,
            "resource",
            "simpoint",
            "simpoint_repo",
            "bin",
            "simpoint",
        ),
    )

    missing = [path for path in [paths.nemu, paths.simpoint] if not os.path.isfile(path)]
    if missing:
        raise FileNotFoundError(
            "required runtime tool missing: " + ", ".join(missing))
    return paths
