# Hugo static sites in Castle

> **This is a stack — creation-time guidance for writing _new_ sites.**
> A stack is a template + conventions, not a runtime requirement. `castle program
> create --stack hugo` scaffolds from it (via Hugo's own `hugo new site`) and seeds
> the program's default build verb. An existing Hugo site adopted with `castle
> program add` doesn't need this stack — it declares its own `commands:` /
> `build:`. See @docs/registry.md for `commands:`, `stack:` (optional), and `repo:`.

How to build, serve, and manage [Hugo](https://gohugo.io) sites as castle programs.

## Stack

- Generator: Hugo (extended recommended — needed for SCSS/asset processing)
- Build: `hugo --gc --minify` → `public/`
- Served: `manager: caddy` static deployment, in place at `<name>.<gateway.domain>`
- Package manager (only if a theme needs an asset pipeline): pnpm

Hugo has one meaningful dev verb — **build**. It has no native lint/test/type-check,
so the stack advertises only `build` / `install` / `uninstall`; `castle check` and
friends aren't offered (a site can still declare its own, e.g. an HTML linter, under
`commands:` — a declared verb always wins over the stack).

## Create a new site

```bash
castle program create my-site --stack hugo --description "My site"
cd /data/repos/my-site
castle program build my-site      # hugo --gc --minify -> public/
castle apply my-site              # serve at my-site.<gateway.domain>
```

The scaffold delegates the canonical skeleton to `hugo new site` (archetypes/,
content/, layouts/, static/, themes/, hugo.toml) and overlays the pieces a bare
skeleton lacks: minimal `layouts/` so the site **builds and serves without a
theme**, an example `content/posts/hello.md`, a castle-flavored `hugo.toml`
(`baseURL = "/"`, so assets resolve at the root of the site's own subdomain), and a
`.gitignore` for the regenerated `public/` and `resources/`.

Develop with the live server:

```bash
hugo server -D        # http://localhost:1313, rebuilds on save
```

## Adding a theme

Drop a theme under `themes/` (usually a git submodule) and set `theme` in
`hugo.toml`:

```bash
git submodule add https://github.com/<owner>/<theme>.git themes/<theme>
```

Themes with an **asset pipeline** (e.g. Blowfish + Tailwind) need a pre-build step
before `hugo`. Declare it as a two-step `build` in `programs/<name>.yaml` — a
declared `build.commands` overrides the stack's single-step default:

```yaml
build:
  commands:
    - [pnpm, build]          # compile the theme's CSS/JS
    - [hugo, --gc, --minify] # render the site -> public/
  outputs: [public]
```

One-time setup those themes expect (run once in the source tree):

```bash
git submodule update --init --recursive
cd themes/<theme> && pnpm install
```

## Deployment shape

`castle program create --stack hugo` writes:

- **`programs/<name>.yaml`** — `source`, `stack: hugo`, `build.outputs: [public]`.
- **`deployments/statics/<name>.yaml`** — `manager: caddy`, `root: public`,
  `reach: internal` (flip to `public` to also expose over the tunnel).

The gateway serves `<source>/public` in place — no copy, no Node/Hugo process at
runtime. `castle program build` regenerates `public/`; `castle apply` renders the
route and reloads the gateway.

## Adopting an existing Hugo site

No stack needed — adopt the repo and declare how it builds:

```bash
castle program add /path/to/site --name my-site
```

Then set `build.commands` (as above) and add a `manager: caddy` deployment. This is
how a site with a bespoke build (submodule theme + Tailwind) is wired without the
scaffold. See @docs/registry.md.
