# Relationships: requires, repos, and derived predicates

How castle models the relationships between **programs**, **deployments**, and
**repos** — and answers questions like *"is this functional?"*, *"is it fresh?"*,
*"is it deployed?"* — with the smallest possible amount of stored state.

## The governing principle

> **Predicates are always derived. Encode only what is not derivable.**

A *predicate* is a question we ask about a program or deployment: `functional?`,
`fresh?`, `deployed?`. None of these are ever stored — each is a **function** over
data castle already has (git, config, the registry). When a predicate can't be
answered from derived data, find the one missing datum and ask: is it about the
**thing** (a node property) or about a **relationship** (an edge property)? Encode
*only* that datum. Everything else stays computed.

This is the same instinct as `kind` (derived from `manager`) — we don't store what
we can compute, and a relationship that proves real and stable in the derived graph
is a candidate to *promote* into a first-class concept. Diagnostic → evidence →
abstraction, in that order.

## Entities

- **program** — the software catalog entry.
- **deployment** — a program realized on this node (`kind` derived from `manager`).
- **repo** — a git working copy. **Derived** from `git rev-parse --show-toplevel`
  on each program's source; several programs sharing one toplevel is a *monorepo*.
  Never stored.

## The one encoded relation: `requires`

Everything we were calling "substrate", "wiring", or "dependency" is one relation —
**`requires`** ("A must have B to be functional") — with a typed target. The
**kind fixes the meaning and the check**; there is no separate purpose/`for` tag:

| kind | means | checked by |
|------|-------|-----------|
| `system` | the host package/binary must be **installed** | `which <ref>` |
| `deployment` | another deployment must **exist / be running** | registry / config |

```yaml
requires:
  - { kind: system, ref: pandoc }              # today's system_dependencies
  - { kind: deployment, ref: astro-guru, bind: GURU_URL }
  # - { kind: deployment, ref: litellm, version: ">=1" }   # version: FUTURE, unused
```

`system_dependencies` is exactly the `{kind: system}` case and is kept as an alias.

Only encode a `requires` edge that is **not derivable** and that **castle itself
must traverse** for an operation (status, bring-up order, group ops). Do **not**
duplicate what another layer already owns — systemd `Requires=`/`After=` for unit
ordering, uv/pnpm for build graphs. This is *castle's* slice, uncoupled from any
one package ecosystem.

### Env is derived *from* `requires`, never scraped *into* it

Reading dependencies out of env strings is unstable (formats vary; a static
frontend's API URL is baked into its bundle and invisible). The stable direction is
the reverse: from an encoded `{kind: deployment}` requirement castle **generates**
the wiring env — it knows the target's address (`<ref>.<domain>` / its port) and
projects it into the consumer's env, optionally under the var named by `bind`. Same
move as `${public_url}`, one step further. Dependency → env, never env → dependency.

## Derived predicates

Computed on demand from encoded `requires` + git + registry; nothing stored:

- **`functional?`** — every `requires` is satisfied (system installed, deployment
  exists). The unmet ones *are* the node's status (`doctor`/`status`).
- **`fresh?`** — the program's repo is at latest and clean (git status).
- **`deployed?`** — the deployment is active in the registry.

New predicates are just new functions over the same preconditions — there is
nothing to "unify" in storage.

## What's encoded vs derived (the whole surface)

| datum | source | stored? |
|-------|--------|---------|
| repo / monorepo | git toplevel | derived |
| `fresh?` / `deployed?` / `functional?` | git / registry / requires | derived |
| env wiring for a dependency | the `requires` edge + target address | derived |
| fan-in ("widely depended-on") | count of requires | derived |
| a **non-derivable** requirement (frontend→backend, host package) | — | **encoded** (`requires`) |
| the env var to bind a dep's URL to, when non-conventional | — | **encoded** (`requires[].bind`) |

Every irreducible found so far is an **edge** (a relationship); no new **node**
property has been needed yet — a sign the encoded surface stays tiny.
