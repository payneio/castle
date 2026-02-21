import { useState } from "react"
import { Plus, X } from "lucide-react"

const TEMPLATES: Record<string, Record<string, unknown>> = {
  service: {
    run: {
      runner: "python_uv_tool",
      tool: "",
      cwd: "",
      env: {},
    },
    expose: {
      http: {
        internal: { port: 9001 },
        health_path: "/health",
      },
    },
    proxy: {
      caddy: { path_prefix: "/" },
    },
    manage: {
      systemd: {},
    },
  },
  tool: {
    install: {
      path: { alias: "" },
    },
  },
  worker: {
    run: {
      runner: "command",
      argv: [""],
      cwd: "",
    },
    manage: {
      systemd: {},
    },
  },
  empty: {},
}

interface AddComponentProps {
  onAdd: (name: string, config: Record<string, unknown>) => Promise<void>
  existingNames: string[]
}

export function AddComponent({ onAdd, existingNames }: AddComponentProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [template, setTemplate] = useState("service")
  const [port, setPort] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const nameError =
    name && !/^[a-z0-9][a-z0-9-]*$/.test(name)
      ? "lowercase letters, numbers, and hyphens"
      : existingNames.includes(name)
        ? "already exists"
        : ""

  const handleSubmit = async () => {
    if (!name || nameError) return
    setSaving(true)
    setError("")
    try {
      const config: Record<string, unknown> = JSON.parse(
        JSON.stringify(TEMPLATES[template] ?? {})
      )
      if (description) config.description = description

      // Fill in template-specific fields
      if (template === "service") {
        const run = config.run as Record<string, unknown>
        run.tool = name
        run.cwd = name
        const proxy = (config.proxy as Record<string, Record<string, string>>).caddy
        proxy.path_prefix = `/${name}`
        if (port) {
          const expose = (config.expose as Record<string, Record<string, Record<string, number>>>)
          expose.http.internal.port = parseInt(port, 10)
        }
      } else if (template === "tool") {
        const install = (config.install as Record<string, Record<string, string>>).path
        install.alias = name
      }

      await onAdd(name, config)
      setName("")
      setDescription("")
      setPort("")
      setOpen(false)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full flex items-center justify-center gap-2 p-4 border border-dashed border-[var(--border)] rounded-lg text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
      >
        <Plus size={16} /> Add component
      </button>
    )
  }

  return (
    <div className="bg-[var(--card)] border border-[var(--primary)] rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">New component</h3>
        <button onClick={() => setOpen(false)} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X size={16} />
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded px-3 py-1.5">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value.toLowerCase())}
            placeholder="my-service"
            autoFocus
            className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
          />
          {nameError && <p className="text-xs text-red-400 mt-1">{nameError}</p>}
        </Field>

        <Field label="Template">
          <select
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"
          >
            <option value="service">Service (FastAPI + systemd + Caddy)</option>
            <option value="tool">Tool (PATH install)</option>
            <option value="worker">Worker (systemd, no HTTP)</option>
            <option value="empty">Empty</option>
          </select>
        </Field>
      </div>

      <Field label="Description">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What does this component do?"
          className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"
        />
      </Field>

      {template === "service" && (
        <Field label="Port">
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="9001"
            className="w-32 bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
          />
        </Field>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={!name || !!nameError || saving}
          className="flex items-center gap-1.5 px-4 py-1.5 text-sm rounded bg-green-700 hover:bg-green-600 text-white transition-colors disabled:opacity-40"
        >
          <Plus size={14} /> Add
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {children}
    </div>
  )
}
