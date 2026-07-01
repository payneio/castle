"""Re-export from castle-core for backward compatibility."""

from castle_core.manifest import *  # noqa: F401, F403
from castle_core.manifest import (  # noqa: F401 — explicit re-exports for type checkers
    BuildSpec,
    Capability,
    CommandsSpec,
    DefaultsSpec,
    EnvMap,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    JobSpec,
    ManageSpec,
    ProgramSpec,
    ReadinessHttpGet,
    RestartPolicy,
    RunBase,
    RunCommand,
    RunCompose,
    RunContainer,
    RunNode,
    RunPython,
    RunRemote,
    RunSpec,
    ServiceSpec,
    SystemdSpec,
)
