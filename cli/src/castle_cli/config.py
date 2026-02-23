"""Re-export from castle-core for backward compatibility."""

from castle_core.config import *  # noqa: F401, F403
from castle_core.config import (  # noqa: F401 — explicit re-exports for type checkers
    CASTLE_HOME,
    GENERATED_DIR,
    SECRETS_DIR,
    CastleConfig,
    GatewayConfig,
    ensure_dirs,
    find_castle_root,
    load_config,
    resolve_env_vars,
    save_config,
)
