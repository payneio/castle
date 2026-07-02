# Web Frontends in Castle

> **This is a stack — creation-time guidance for writing _new_ frontends.**
> A stack is a template + conventions, not a runtime requirement. `castle program create
> --stack react-vite` scaffolds from it and seeds the program's default dev-verb
> commands. An existing frontend adopted with `castle program add` doesn't need this
> stack — it declares its own `commands:`. See @docs/registry.md for
> `commands:`, `stack:` (optional), and `repo:`.

How to build, serve, and manage web frontends as castle programs.

## Stack

- Build: Vite 6
- Language: TypeScript 5.8 (strict)
- Framework: React 19
- Routing: React Router 7
- Styling: Tailwind CSS 4 (`@tailwindcss/vite` plugin)
- Components: shadcn/ui (new-york style) + Radix UI primitives
- Icons: Lucide React
- Server state: TanStack React Query 5
- Forms: React Hook Form + Zod validation
- Testing: Vitest + Testing Library
- Package manager: pnpm

## Scaffolding a new frontend

```bash
# Create the project
mkdir /data/repos/my-frontend && cd /data/repos/my-frontend
pnpm create vite . --template react-ts

# Core dependencies
pnpm add react-router react-router-dom \
         @tanstack/react-query \
         tailwindcss @tailwindcss/vite \
         class-variance-authority clsx tailwind-merge \
         lucide-react sonner zod \
         react-hook-form @hookform/resolvers

# Dev dependencies
pnpm add -D vitest jsdom @testing-library/react @testing-library/jest-dom \
            @testing-library/user-event

# shadcn/ui
pnpm dlx shadcn@latest init
```

## Vite config

```ts
// vite.config.ts
import path from "path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  // Castle sets VITE_BASE=/ at build time (every frontend serves at its
  // subdomain root). Reading it here keeps the bundle.s absolute asset
  // URLs resolving at the root — no hand-tuning.
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
```

> **Serving behind the gateway.** A static frontend is served at its own subdomain
> — `<name>.<gateway.domain>` — rooted at `/`, so `VITE_BASE` is always `/`. Castle's
> `react-vite` build passes `VITE_BASE=/`, and a `vite.config` that reads it (above)
> works unchanged. (Frontends are no longer mounted under a `/<name>/` path.)

## Project layout

```
my-frontend/
├── src/
│   ├── main.tsx                 # ReactDOM.createRoot mount
│   ├── App.tsx                  # Root: QueryClientProvider + RouterProvider
│   ├── index.css                # Tailwind imports + CSS custom properties
│   ├── router/
│   │   ├── index.tsx            # createBrowserRouter
│   │   └── routes.tsx           # Route tree
│   ├── components/
│   │   └── ui/                  # shadcn/ui components
│   ├── services/api/
│   │   ├── client.ts            # Typed fetch wrapper
│   │   └── hooks/               # React Query hooks per resource
│   ├── hooks/                   # App-level hooks
│   ├── contexts/                # React context providers
│   ├── lib/
│   │   ├── utils.ts             # cn() helper
│   │   └── queryClient.ts       # Query client config
│   ├── types/                   # Shared TypeScript types
│   └── schemas/                 # Zod schemas
├── public/                      # Static assets (favicon, manifest.json)
├── index.html                   # SPA entry point
├── package.json
├── vite.config.ts
├── tsconfig.json
├── vitest.config.ts
├── components.json              # shadcn/ui config
└── .env                         # VITE_API_BASE_URL etc.
```

## Build commands

```bash
pnpm run dev          # Vite dev server (:5173), HMR
pnpm run build        # tsc -b && vite build → dist/
pnpm run preview      # Serve production build locally
pnpm run type-check   # tsc --noEmit
pnpm run lint         # ESLint
pnpm run test         # Vitest
pnpm run check        # lint + type-check + test
```

The `build` output is a static SPA in `dist/` — just HTML, JS, and CSS files.

## Registering as a program

A frontend program has a `build` spec (produces static output). Register it in
`programs/<name>.yaml`, plus a `deployments/<name>.yaml` with `manager: caddy`
(derived **kind: static**) that names the built directory in `root:` — no `run`
block, since Caddy serves the build output directly.

```yaml
# programs/my-frontend.yaml
description: Web dashboard
source: /data/repos/my-frontend
build:
  commands:
    - ["pnpm", "build"]
  outputs:
    - dist/
```
```yaml
# deployments/my-frontend.yaml (manager: caddy → kind: static)
program: my-frontend
manager: caddy
root: dist    # served at my-frontend.<gateway.domain>
```

For production, Caddy serves the build output **in place** from the program's
repo (`<source>/<root>`) — no Node process and no copy into a central directory.
See [Serving with Caddy](#serving-with-caddy) below.

For development with Vite's dev server, use a `manager: systemd` deployment with
the `node` launcher instead:

```yaml
# deployments/my-frontend.yaml (dev — manager: systemd, node launcher → kind: service)
program: my-frontend
manager: systemd
run:
  launcher: node
  script: dev
  package_manager: pnpm
expose:
  http:
    internal: { port: 5173 }
proxy: true   # expose the dev server at my-frontend.<gateway.domain>
```

See @docs/registry.md for the full registry reference.

## Serving with Caddy

For production, the static build output is served by Caddy rather than a Node
process. You do **not** write this block by hand — `castle apply` generates it.
The flow:

1. You build the frontend with `castle program build <name>` (deploy does **not**
   build — it only points Caddy at `dist/`).
2. The Caddyfile generator emits a route per `manager: caddy` deployment (kind
   **static**), rooted **in place** at `<source>/<root>` — no copy. Each static
   frontend is served at its own subdomain `<name>.<gateway.domain>` (the
   dashboard, `castle`, is also the target of the `:9000` redirect).

The build is run with `VITE_BASE=/`, so a `vite.config` that reads it (see
[Vite config](#vite-config)) emits root-relative asset URLs. The generated block
(in `~/.castle/artifacts/specs/Caddyfile`) is a host matcher inside the
`*.<domain>` site:

```caddyfile
@host_my_frontend host my-frontend.example.com
handle @host_my_frontend {
    root * /data/repos/my-frontend/dist
    try_files {path} /index.html
    file_server
}
```

The `try_files {path} /index.html` directive is essential for SPA routing —
it falls back to `index.html` for any path that doesn't match a static file,
letting React Router handle client-side routes. The subdomain is the program name,
not hand-configured.

## API integration

Frontends talk to castle services via environment variables injected at build
time. Vite exposes variables prefixed with `VITE_`:

```bash
# .env
VITE_API_BASE_URL=http://localhost:9001
```

```ts
// src/services/api/client.ts
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:9001"

class ApiClient {
  private baseUrl: string

  constructor(baseUrl = BASE_URL) {
    this.baseUrl = baseUrl
  }

  async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`)
    if (!resp.ok) throw new ApiError(resp.status, await resp.text())
    return resp.json()
  }

  // post<T>, put<T>, delete<T>, etc.
}

export const apiClient = new ApiClient()
```

When served behind the castle gateway, the API base URL can use the gateway's
proxy paths (e.g., `/central-context/`) instead of direct ports, avoiding CORS.

## React Query setup

```ts
// src/lib/queryClient.ts
import { QueryClient } from "@tanstack/react-query"

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,    // 5 minutes
      gcTime: 10 * 60 * 1000,      // 10 minutes
      retry: 1,
    },
  },
})
```

```ts
// src/services/api/hooks/useThings.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiClient } from "../client"

export function useThings() {
  return useQuery({
    queryKey: ["things"],
    queryFn: () => apiClient.get<Thing[]>("/things"),
  })
}

export function useCreateThing() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateThing) => apiClient.post<Thing>("/things", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["things"] }),
  })
}
```

## shadcn/ui setup

Initialize with the `components.json` config:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/index.css",
    "baseColor": "neutral",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "iconLibrary": "lucide"
}
```

Add components as needed:

```bash
pnpm dlx shadcn@latest add button card dialog sidebar
```

Components are copied into `src/components/ui/` as source files you own and can
modify. They use Radix UI primitives underneath, with Tailwind for styling.

## Dark mode

Use CSS custom properties with a `.dark` class on `<html>`:

```css
/* src/index.css */
@import "tailwindcss";

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --primary: oklch(0.205 0 0);
  /* ... */
}

.dark {
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);
  --primary: oklch(0.922 0 0);
  /* ... */
}
```

Toggle via a React context that persists the preference to `localStorage`.

## Testing

```ts
// vitest.config.ts
import { defineConfig } from "vitest/config"
import path from "path"

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    exclude: ["dist/**"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
})
```

```bash
pnpm run test              # Single run
pnpm run test:ui           # Interactive UI
pnpm run test:coverage     # With coverage report
```
