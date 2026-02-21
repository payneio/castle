import { useMemo, useState } from "react"
import { Check, Loader2, Save, Trash2 } from "lucide-react"
import type { ComponentDetail } from "@/types"
import { SecretsEditor } from "./SecretsEditor"

interface ComponentFieldsProps {
  component: ComponentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

const SECRET_RE = /^\$\{secret:([^}]+)\}$/

export function ComponentFields({ component, onSave, onDelete }: ComponentFieldsProps) {
  const m = component.manifest
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const allEnv: Record<string, string> =
    ((m.run as Record<string, unknown>)?.env as Record<string, string>) ?? {}

  // Split into plain env vars and secret references
  const { initialEnv, initialSecrets } = useMemo(() => {
    const env: Record<string, string> = {}
    const secrets: Record<string, string> = {}
    for (const [key, val] of Object.entries(allEnv)) {
      const match = SECRET_RE.exec(val)
      if (match) {
        secrets[key] = match[1]
      } else {
        env[key] = val
      }
    }
    return { initialEnv: env, initialSecrets: secrets }
  }, [])

  const [runEnv, setRunEnv] = useState<Record<string, string>>(initialEnv)
  const [secrets, setSecrets] = useState<Record<string, string>>(initialSecrets)

  const [description, setDescription] = useState(m.description as string ?? "")
  const [port, setPort] = useState(
    String(
      ((m.expose as Record<string, unknown>)?.http as Record<string, unknown>)
        ?.internal as Record<string, unknown>
        ? (((m.expose as Record<string, unknown>)?.http as Record<string, unknown>)
            ?.internal as Record<string, number>)?.port ?? ""
        : ""
    )
  )
  const [proxyPath, setProxyPath] = useState(
    ((m.proxy as Record<string, unknown>)?.caddy as Record<string, string>)?.path_prefix ?? ""
  )
  const [healthPath, setHealthPath] = useState(
    ((m.expose as Record<string, unknown>)?.http as Record<string, string>)?.health_path ?? ""
  )

  const runner = (m.run as Record<string, unknown>)?.runner as string | undefined

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = { ...m }
      delete config.id
      delete config.roles
      config.description = description || undefined

      // Merge plain env + secret references back together
      if (config.run && typeof config.run === "object") {
        const mergedEnv: Record<string, string> = { ...runEnv }
        for (const [envKey, secretName] of Object.entries(secrets)) {
          mergedEnv[envKey] = `\${secret:${secretName}}`
        }
        config.run = { ...config.run as Record<string, unknown>, env: mergedEnv }
      }

      if (port) {
        const portNum = parseInt(port, 10)
        if (!isNaN(portNum)) {
          config.expose = {
            http: {
              internal: { port: portNum },
              ...(healthPath ? { health_path: healthPath } : {}),
            },
          }
        }
      }

      if (proxyPath) {
        config.proxy = { caddy: { path_prefix: proxyPath } }
      } else {
        delete config.proxy
      }

      await onSave(component.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Description">
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"
        />
      </Field>

      {runner && (
        <Field label="Runner">
          <span className="text-sm font-mono text-[var(--muted)]">
            {runner}
            {(m.run as Record<string, string>)?.tool && (
              <> &middot; {(m.run as Record<string, string>).tool}</>
            )}
          </span>
        </Field>
      )}

      {(component.managed || port) && (
        <Field label="Port">
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="e.g. 9001"
            className="w-32 bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
          />
        </Field>
      )}

      {(component.managed || healthPath) && (
        <Field label="Health path">
          <input
            value={healthPath}
            onChange={(e) => setHealthPath(e.target.value)}
            placeholder="/health"
            className="w-48 bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
          />
        </Field>
      )}

      <Field label="Proxy path">
        <input
          value={proxyPath}
          onChange={(e) => setProxyPath(e.target.value)}
          placeholder="/my-service"
          className="w-48 bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
        />
      </Field>

      {runner && (
        <Field label="Environment">
          <div className="space-y-2">
            {Object.entries(runEnv).map(([key, val]) => (
              <div key={key} className="flex items-center gap-2">
                <input
                  value={key}
                  readOnly
                  className="w-56 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono text-[var(--muted)]"
                />
                <span className="text-[var(--muted)]">=</span>
                <input
                  value={val}
                  onChange={(e) =>
                    setRunEnv((prev) => ({ ...prev, [key]: e.target.value }))
                  }
                  className="flex-1 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
                />
                <button
                  onClick={() =>
                    setRunEnv((prev) => {
                      const next = { ...prev }
                      delete next[key]
                      return next
                    })
                  }
                  className="text-red-400 hover:text-red-300 p-0.5"
                  title="Remove"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
            <button
              onClick={() => {
                const key = prompt("Variable name:")
                if (key) setRunEnv((prev) => ({ ...prev, [key]: "" }))
              }}
              className="text-xs text-[var(--primary)] hover:underline"
            >
              + Add variable
            </button>
          </div>
        </Field>
      )}

      {runner && (
        <Field label="Secrets">
          <SecretsEditor secrets={secrets} onSecretsChange={setSecrets} />
        </Field>
      )}

      <Field label="Systemd">
        <span className="text-sm text-[var(--muted)]">
          {component.managed ? "Yes" : "No"}
        </span>
      </Field>

      <div className="flex items-center justify-between pt-3 border-t border-[var(--border)]">
        {onDelete ? (
          <button
            onClick={() => {
              if (confirm(`Delete component "${component.id}" from castle.yaml?`)) {
                onDelete(component.id)
              }
            }}
            className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300"
          >
            <Trash2 size={12} /> Remove component
          </button>
        ) : (
          <div />
        )}
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 text-white transition-colors disabled:opacity-40"
        >
          {saving ? (
            <Loader2 size={14} className="animate-spin" />
          ) : saved ? (
            <Check size={14} />
          ) : (
            <Save size={14} />
          )}
          {saved ? "Saved" : "Save"}
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4">
      <label className="w-32 shrink-0 text-sm font-medium pt-1.5">{label}</label>
      <div className="flex-1">{children}</div>
    </div>
  )
}
