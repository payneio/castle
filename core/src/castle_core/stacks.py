"""Stack protocol — lifecycle actions for each development stack."""

from __future__ import annotations

import asyncio
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from castle_core.config import USER_TOOL_PATH_DIRS
from castle_core.manifest import ProgramSpec
from castle_core.toolchains import ToolchainError, resolve_node_bin

DEV_ACTIONS = ["build", "test", "lint", "format", "type-check", "check", "run"]
INSTALL_ACTIONS = ["install", "uninstall"]
ALL_ACTIONS = DEV_ACTIONS + INSTALL_ACTIONS

# Verbs a stack handler can provide (everything except `run`, which is declared-only).
_STACK_VERBS = {
    "build",
    "test",
    "lint",
    "format",
    "type-check",
    "check",
    "install",
    "uninstall",
}
# Verbs whose handler method name differs from the verb spelling.
_VERB_METHOD = {"type-check": "type_check"}


@dataclass
class ActionResult:
    """Result of a program lifecycle action."""

    program: str
    action: str
    status: str  # "ok" | "error"
    output: str = ""


def _build_env(node_source: Path | None = None) -> dict[str, str]:
    """Build a subprocess env with user tool dirs on PATH.

    ``node_source`` is the program's source dir: if it pins a node version (see
    :mod:`castle_core.toolchains`), that node's bin dir goes on the front of PATH so
    the verb uses the program's node instead of whatever ambient node the caller
    happens to have (the CLI inherits your shell's; the castle-api build executor's
    default PATH has none). Raises :class:`ToolchainError` if the pin isn't installed.
    """
    env = os.environ.copy()
    dirs = [str(d) for d in USER_TOOL_PATH_DIRS if d.exists()]
    node_bin = resolve_node_bin(node_source)
    if node_bin is not None:
        dirs.insert(0, str(node_bin))
    if dirs:
        env["PATH"] = ":".join(dirs) + ":" + env.get("PATH", "")
    return env


async def _run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Run a subprocess and return (returncode, combined output).

    The verb runs in ``cwd`` (the program source), so that dir doubles as the node
    pin source — a pinned-but-missing node fails loud here rather than as a cryptic
    ``node: not found`` mid-build."""
    try:
        run_env = _build_env(cwd)
    except ToolchainError as e:
        return 1, str(e)
    if env:
        run_env.update(env)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=run_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, (stdout or b"").decode()


def _vite_base(name: str) -> str:
    """The base path a castle-served static frontend builds against.

    Every frontend now serves at the **root of its own subdomain**
    (`<name>.<gateway.domain>`), so the base is always '/'. Exposed to the build
    as VITE_BASE (the vite.config reads `base: process.env.VITE_BASE ?? '/'`)."""
    return "/"


def _source_dir(comp: ProgramSpec, root: Path) -> Path:
    """Resolve source directory, raising ValueError if absent."""
    if not comp.source:
        raise ValueError("No source directory")
    return root / comp.source


class StackHandler:
    """Base class — subclasses implement each lifecycle action."""

    # Whether this stack owns *persistent external state* (a database schema, a
    # bucket, …) that outlives a code delete. Drives whether `castle delete`
    # surfaces a data remnant / honors `--purge-data`. Overridden to True by the
    # stacks whose `teardown` actually destroys something.
    owns_data: bool = False

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def format(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def type_check(
        self, name: str, comp: ProgramSpec, root: Path
    ) -> ActionResult:
        raise NotImplementedError

    async def check(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Composite: lint + type-check + test. Runs all, reports first failure."""
        for action_fn, action_name in [
            (self.lint, "lint"),
            (self.type_check, "type-check"),
            (self.test, "test"),
        ]:
            result = await action_fn(name, comp, root)
            if result.status != "ok":
                return ActionResult(
                    program=name,
                    action="check",
                    status="error",
                    output=f"{action_name} failed:\n{result.output}",
                )
        return ActionResult(program=name, action="check", status="ok")

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def teardown(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Destroy the persistent external state this program's stack created
        (database schema, blobs, …) — the irreversible counterpart to a code
        delete. Distinct from `uninstall` (which only takes a program offline).

        Default: nothing to tear down. Only stacks that set ``owns_data`` and own
        durable state override this; `castle delete --purge-data` invokes it.
        """
        return ActionResult(
            program=name,
            action="teardown",
            status="ok",
            output=f"{name}: no persistent state to tear down.",
        )


class PythonHandler(StackHandler):
    """Handler for python-cli and python-fastapi stacks."""

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "sync"], src)
        return ActionResult(
            program=name,
            action="build",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        if not (src / "tests").exists():
            return ActionResult(
                program=name,
                action="test",
                status="ok",
                output="No tests directory found, skipping.",
            )
        rc, output = await _run(["uv", "run", "pytest", "tests/", "-v"], src)
        return ActionResult(
            program=name,
            action="test",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "run", "ruff", "check", "."], src)
        return ActionResult(
            program=name,
            action="lint",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def format(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "run", "ruff", "format", "."], src)
        return ActionResult(
            program=name,
            action="format",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def type_check(
        self, name: str, comp: ProgramSpec, root: Path
    ) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "run", "pyright"], src)
        return ActionResult(
            program=name,
            action="type-check",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        pkg_spec = str(src)
        if comp.install_extras:
            pkg_spec += "[" + ",".join(comp.install_extras) + "]"
        rc, output = await _run(
            ["uv", "tool", "install", "--editable", pkg_spec, "--force"], src
        )
        return ActionResult(
            program=name,
            action="install",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        pkg_name = src.name
        pyproject = src / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            pkg_name = data.get("project", {}).get("name", pkg_name)
        rc, output = await _run(["uv", "tool", "uninstall", pkg_name], src)
        return ActionResult(
            program=name,
            action="uninstall",
            status="ok" if rc == 0 else "error",
            output=output,
        )


# pnpm (10+) runs a deps-status check before `pnpm <script>` that wants to purge +
# reinstall node_modules and aborts when there's no TTY
# (ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY). It's a false positive for a build —
# the verb builds, it doesn't install — so skip the check and use the existing
# modules. (The env-var form isn't honored; the CLI flag is.) CI=true guards any
# other interactive prompt.
_PNPM_ENV = {"CI": "true"}


def _pnpm(*args: str) -> list[str]:
    """A pnpm argv with the pre-run deps check disabled."""
    return ["pnpm", "--config.verify-deps-before-run=false", *args]


class ReactViteHandler(StackHandler):
    """Handler for react-vite stack."""

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        # Build against the gateway serve root so absolute asset URLs resolve at /
        # (vite.config reads VITE_BASE=/). Removes the hand-tuned-base footgun.
        rc, output = await _run(
            _pnpm("build"), src, env={**_PNPM_ENV, "VITE_BASE": _vite_base(name)}
        )
        return ActionResult(
            program=name,
            action="build",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(_pnpm("test"), src, env=_PNPM_ENV)
        return ActionResult(
            program=name,
            action="test",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(_pnpm("lint"), src, env=_PNPM_ENV)
        return ActionResult(
            program=name,
            action="lint",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def format(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(_pnpm("format"), src, env=_PNPM_ENV)
        return ActionResult(
            program=name,
            action="format",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def type_check(
        self, name: str, comp: ProgramSpec, root: Path
    ) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(_pnpm("type-check"), src, env=_PNPM_ENV)
        return ActionResult(
            program=name,
            action="type-check",
            status="ok" if rc == 0 else "error",
            output=output,
        )

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Build the static assets in place. The gateway serves them directly from
        <source>/<build.outputs[0]> — no copy into a central content dir."""
        result = await self.build(name, comp, root)
        if result.status != "ok":
            return ActionResult(
                program=name,
                action="install",
                status="error",
                output=f"Build failed:\n{result.output}",
            )
        outputs = comp.build.outputs if comp.build else []
        if not outputs:
            return ActionResult(
                program=name,
                action="install",
                status="error",
                output="No build outputs configured.",
            )
        dist = _source_dir(comp, root) / outputs[0]
        return ActionResult(
            program=name,
            action="install",
            status="ok",
            output=f"Built; served in place from {dist}",
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Static frontends have no install footprint to remove (served in place).

        Deactivating one means dropping its gateway route — handled by removing the
        program from the registry, not by deleting build output."""
        return ActionResult(
            program=name,
            action="uninstall",
            status="ok",
            output=f"{name}: served in place; nothing to uninstall.",
        )


def _migration_version(path: Path) -> str:
    """The version key of a migration file — the leading token before '_'.

    e.g. ``0001_init.sql`` → ``0001``. Recorded in ``schema_migrations`` so a
    redeploy applies only the unapplied files.
    """
    return path.name.split("_", 1)[0]


def plan_migrations(files: list[Path], applied: set[str]) -> list[Path]:
    """Order migrations by filename and drop any whose version is already applied.

    Forward-only and idempotent (mirrors Patch's runner): re-running applies only
    new files, never re-applies an existing one. Pure — no DB — so it's unit-tested
    without a substrate.
    """
    return [
        p
        for p in sorted(files, key=lambda x: x.name)
        if _migration_version(p) not in applied
    ]


def _substrate_db_url() -> str | None:
    """Best-effort Postgres URL for the shared substrate.

    Prefers an explicit ``SUPABASE_DB_URL``; otherwise builds one from the
    generated ``SUPABASE_POSTGRES_PASSWORD`` secret against the substrate's direct
    Postgres port. The self-hosted substrate publishes Postgres on host **5433**
    (5432 is taken by another Postgres on this node — see the substrate compose),
    overridable via ``SUPABASE_DB_HOST_PORT``. Returns None if neither an explicit
    URL nor the secret is available (build then fails loud with guidance).
    """
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    from castle_core.config import read_secret

    pw = read_secret("SUPABASE_POSTGRES_PASSWORD")
    if pw:
        port = os.environ.get("SUPABASE_DB_HOST_PORT", "5433")
        return f"postgresql://postgres:{pw}@localhost:{port}/postgres"
    return None


def app_schema(name: str) -> str:
    """The dedicated Postgres schema a supabase app owns.

    Each app is isolated in its own schema (named after the program, ``-``→``_``
    for a valid unquoted identifier) rather than sharing ``public``. That gives a
    clean teardown (``drop schema … cascade``) and a per-app ``schema_migrations``
    so migration version tokens never collide across apps.
    """
    return name.replace("-", "_")


# The privilege grant that makes an app schema reachable through PostgREST — the
# canonical Supabase "expose a custom schema" snippet. Idempotent; run before
# migrations so `alter default privileges` also covers the tables they create.
# Exposure ALSO requires the schema in the substrate's PGRST_DB_SCHEMAS — castle
# derives that from the registered supabase apps (`${supabase_app_schemas}`), so a
# newly-added app needs a `castle deploy` + substrate restart to become routable.
def _schema_setup_sql(schema: str) -> str:
    roles = "anon, authenticated, service_role"
    return (
        f'create schema if not exists "{schema}";\n'
        f'grant usage on schema "{schema}" to {roles};\n'
        f'grant all on all tables in schema "{schema}" to {roles};\n'
        f'grant all on all routines in schema "{schema}" to {roles};\n'
        f'grant all on all sequences in schema "{schema}" to {roles};\n'
        f'alter default privileges in schema "{schema}" '
        f"grant all on tables to {roles};\n"
        f'alter default privileges in schema "{schema}" '
        f"grant all on routines to {roles};\n"
        f'alter default privileges in schema "{schema}" '
        f"grant all on sequences to {roles};\n"
    )


class SupabaseHandler(StackHandler):
    """Stack handler for supabase apps (migrations + edge functions + static UI).

    Each app is isolated in its **own Postgres schema** (``app_schema(name)``): the
    migration runner creates + grants that schema, tracks applied versions in
    ``<schema>.schema_migrations``, and runs each migration with ``search_path``
    set to it — so migration SQL is schema-agnostic and version tokens never
    collide across apps. The static UI is served in place by the gateway (no
    process), so install/uninstall are no-ops like a frontend. `teardown` drops the
    schema (and thus every object the app created) in one shot.
    """

    owns_data = True

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Apply unapplied migrations into the app's own schema (idempotent)."""
        src = _source_dir(comp, root)
        schema = app_schema(name)
        mig_dir = src / "migrations"
        files = sorted(mig_dir.glob("*.sql")) if mig_dir.is_dir() else []

        psql = shutil.which("psql")
        url = _substrate_db_url()
        if not psql:
            return ActionResult(
                name,
                "build",
                "error",
                "psql not found — install postgresql-client to run migrations.",
            )
        if not url:
            return ActionResult(
                name,
                "build",
                "error",
                "No substrate DB URL. Set SUPABASE_DB_URL, or generate secrets "
                "(scripts/gen-keys.py) so SUPABASE_POSTGRES_PASSWORD exists.",
            )

        # Ensure the app's schema exists, is PostgREST-exposable (grants), and has
        # its own tracking table — then read applied versions from THAT schema.
        rc, out = await _run(
            [
                psql,
                url,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                _schema_setup_sql(schema),
                "-c",
                f'create table if not exists "{schema}".schema_migrations '
                "(version text primary key, applied_at timestamptz default now())",
            ],
            src,
        )
        if rc != 0:
            return ActionResult(name, "build", "error", f"connect/init failed:\n{out}")

        if not files:
            return ActionResult(
                name, "build", "ok", f"Schema '{schema}' ready. No migrations to apply."
            )

        rc, out = await _run(
            [
                psql,
                url,
                "-tA",
                "-c",
                f'select version from "{schema}".schema_migrations',
            ],
            src,
        )
        if rc != 0:
            return ActionResult(
                name, "build", "error", f"read migrations failed:\n{out}"
            )
        applied = {line.strip() for line in out.splitlines() if line.strip()}

        pending = plan_migrations(files, applied)
        if not pending:
            return ActionResult(
                name,
                "build",
                "ok",
                f"All migrations already applied (schema {schema}).",
            )

        log = []
        for path in pending:
            version = _migration_version(path)
            # search_path → the app schema, so migration SQL can write unqualified
            # names and they land in the app's schema (not public). File +
            # version-insert in ONE transaction: a failed migration records
            # nothing, so the next build safely retries it.
            rc, out = await _run(
                [
                    psql,
                    url,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "--single-transaction",
                    "-c",
                    f'set search_path to "{schema}", public',
                    "-f",
                    str(path),
                    "-c",
                    f'insert into "{schema}".schema_migrations(version) '
                    f"values('{version}')",
                ],
                src,
            )
            if rc != 0:
                log.append(f"✗ {path.name}\n{out}")
                return ActionResult(name, "build", "error", "\n".join(log))
            log.append(f"✓ {path.name}")
        return ActionResult(name, "build", "ok", "\n".join(log))

    async def teardown(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Drop the app's schema and everything in it (tables, its own
        schema_migrations, functions) in one statement — total and knowable
        because the app owns exactly one schema. The substrate's PGRST_DB_SCHEMAS
        drops the (now-absent) schema on the next `castle deploy` + restart.
        """
        schema = app_schema(name)
        psql = shutil.which("psql")
        url = _substrate_db_url()
        if not psql or not url:
            return ActionResult(
                name,
                "teardown",
                "error",
                f"Cannot drop schema '{schema}': psql or substrate DB URL "
                'unavailable. Drop it manually: drop schema "%s" cascade;' % schema,
            )
        cwd = src if (src := (root / comp.source if comp.source else None)) else root
        rc, out = await _run(
            [
                psql,
                url,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f'drop schema if exists "{schema}" cascade',
            ],
            cwd,
        )
        if rc != 0:
            return ActionResult(name, "teardown", "error", f"drop failed:\n{out}")
        return ActionResult(
            name,
            "teardown",
            "ok",
            f"Dropped schema '{schema}' (all tables + rows). Run `castle deploy` "
            "and restart the substrate to prune it from PGRST_DB_SCHEMAS.",
        )

    async def _deno(
        self, name: str, action: str, comp: ProgramSpec, root: Path, args: list[str]
    ) -> ActionResult:
        """Run a `deno` subcommand over functions/, or skip cleanly if deno absent."""
        src = _source_dir(comp, root)
        fns = src / "functions"
        deno = shutil.which("deno")
        if not deno or not fns.is_dir():
            return ActionResult(
                name, action, "ok", f"{action}: skipped (no deno/functions)"
            )
        rc, out = await _run([deno, *args, "functions/"], src)
        return ActionResult(name, action, "ok" if rc == 0 else "error", out)

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        return await self._deno(name, "test", comp, root, ["test", "--allow-all"])

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        return await self._deno(name, "lint", comp, root, ["lint"])

    async def format(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        return await self._deno(name, "format", comp, root, ["fmt"])

    async def type_check(
        self, name: str, comp: ProgramSpec, root: Path
    ) -> ActionResult:
        return await self._deno(name, "type-check", comp, root, ["check"])

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Static UI is served in place by the gateway; nothing to install."""
        return ActionResult(
            name, "install", "ok", f"{name}: served in place at /{name}/."
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        return ActionResult(
            name, "uninstall", "ok", f"{name}: served in place; nothing to remove."
        )


HANDLERS: dict[str, StackHandler] = {
    "python-cli": PythonHandler(),
    "python-fastapi": PythonHandler(),
    "react-vite": ReactViteHandler(),
    "supabase": SupabaseHandler(),
}


def get_handler(stack: str | None) -> StackHandler | None:
    """Get the handler for a given stack, or None if unsupported."""
    if stack is None:
        return None
    return HANDLERS.get(stack)


def available_stacks() -> list[str]:
    """The stack names castle has handlers for — the single source of truth for the
    CLI ``--stack`` choices, the ``GET /stacks`` endpoint, and the dashboard select.
    """
    return sorted(HANDLERS)


def _declared_commands(comp: ProgramSpec, verb: str) -> list[list[str]] | None:
    """Declared argv-lists for a verb, or None.

    `build` is declared via BuildSpec.commands; every other verb via CommandsSpec.
    """
    if verb == "build":
        if comp.build and comp.build.commands:
            return comp.build.commands
        return None
    if comp.commands is not None:
        return comp.commands.for_verb(verb)
    return None


def _stack_provides(comp: ProgramSpec, verb: str) -> bool:
    """Whether the program's stack handler can run this verb."""
    return (
        bool(comp.source)
        and verb in _STACK_VERBS
        and get_handler(comp.stack) is not None
    )


def is_available(comp: ProgramSpec, verb: str) -> bool:
    """Whether a verb can be run for a program (declared command or stack default)."""
    if _declared_commands(comp, verb) is not None:
        return True
    if verb == "check":
        return any(is_available(comp, sub) for sub in ("lint", "type-check", "test"))
    return _stack_provides(comp, verb)


def available_actions(comp: ProgramSpec) -> list[str]:
    """Return the list of verbs available for a program (resolution-aware)."""
    if not comp.source:
        return []
    return [verb for verb in ALL_ACTIONS if is_available(comp, verb)]


async def _run_declared(
    name: str, verb: str, cmds: list[list[str]], src: Path
) -> ActionResult:
    """Run declared argv-lists in sequence; stop at the first failure."""
    outputs: list[str] = []
    for argv in cmds:
        rc, output = await _run(argv, src)
        outputs.append(output)
        if rc != 0:
            return ActionResult(
                program=name, action=verb, status="error", output="".join(outputs)
            )
    return ActionResult(program=name, action=verb, status="ok", output="".join(outputs))


async def run_action(
    verb: str, name: str, comp: ProgramSpec, root: Path
) -> ActionResult:
    """Resolve and run a verb: declared command → stack default → unavailable.

    This is the single entry point callers should use; it replaces reaching for
    get_handler(...).<method>(...) directly so the override logic stays in one place.
    """
    # `check` is a composite that must respect per-verb overrides — unless the
    # program declares its own `check`, run each available sub-verb via run_action.
    if verb == "check" and _declared_commands(comp, "check") is None:
        subs = [s for s in ("lint", "type-check", "test") if is_available(comp, s)]
        if not subs:
            return ActionResult(
                program=name,
                action="check",
                status="error",
                output="No checkable verbs available.",
            )
        sections: list[str] = []
        for sub in subs:
            result = await run_action(sub, name, comp, root)
            mark = "✓" if result.status == "ok" else "✗"
            body = result.output.strip()
            sections.append(f"{mark} {sub}" + (f"\n{body}" if body else ""))
            if result.status != "ok":
                return ActionResult(
                    program=name,
                    action="check",
                    status="error",
                    output="\n\n".join(sections),
                )
        return ActionResult(
            program=name, action="check", status="ok", output="\n\n".join(sections)
        )

    # 1. Declared command overrides the stack default.
    declared = _declared_commands(comp, verb)
    if declared is not None:
        try:
            src = _source_dir(comp, root)
        except ValueError:
            return ActionResult(
                program=name, action=verb, status="error", output="No source directory"
            )
        return await _run_declared(name, verb, declared, src)

    # 2. Stack default.
    handler = get_handler(comp.stack)
    if handler is not None and verb in _STACK_VERBS:
        method = getattr(handler, _VERB_METHOD.get(verb, verb), None)
        if method is not None:
            return await method(name, comp, root)

    # 3. Unavailable.
    return ActionResult(
        program=name,
        action=verb,
        status="error",
        output=f"Verb '{verb}' is not available for '{name}' "
        f"(no declared command and no stack handler provides it).",
    )
