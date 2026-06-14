import { useState } from "react"
import type { ServiceDetail } from "@/types"
import { runnerLabel } from "@/lib/labels"
import { Field, TextField, FormFooter, useEnvSecrets } from "./fields"

interface Props {
  service: ServiceDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v as Obj) ?? {}

/** Edit a service's deployment config (run / expose / proxy / env). */
export function ServiceFields({ service, onSave, onDelete }: Props) {
  const m = service.manifest
  const run = obj(m.run)
  const internal = obj(obj(obj(m.expose).http).internal)
  const httpExpose = obj(obj(m.expose).http)
  const caddy = obj(obj(m.proxy).caddy)

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [description, setDescription] = useState((m.description as string) ?? "")
  const [runProgram, setRunProgram] = useState(
    (run.program as string) ?? ((run.argv as string[]) ?? []).join(" "),
  )
  const [port, setPort] = useState(internal.port != null ? String(internal.port) : "")
  const [portEnv, setPortEnv] = useState((internal.port_env as string) ?? "")
  const [health, setHealth] = useState((httpExpose.health_path as string) ?? "")
  const [proxyPath, setProxyPath] = useState((caddy.path_prefix as string) ?? "")
  const [proxyHost, setProxyHost] = useState((caddy.host as string) ?? "")

  const { element: envEditor, merged } = useEnvSecrets(obj(obj(m.defaults).env) as Record<string, string>)

  const runner = (run.runner as string) ?? "?"

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      config.description = description || undefined

      // Only python/command run specs are edited here; other runners
      // (container/node/remote) keep their original run block untouched.
      const runOut = obj(config.run)
      if (runner === "command") runOut.argv = runProgram.split(" ").filter(Boolean)
      else if (runner === "python") runOut.program = runProgram
      config.run = runOut

      if (port) {
        config.expose = {
          http: {
            internal: {
              port: parseInt(port, 10),
              ...(portEnv ? { port_env: portEnv } : {}),
            },
            ...(health ? { health_path: health } : {}),
          },
        }
      } else {
        delete config.expose
      }

      if (proxyPath || proxyHost) {
        config.proxy = {
          caddy: {
            ...(proxyPath ? { path_prefix: proxyPath } : {}),
            ...(proxyHost ? { host: proxyHost } : {}),
          },
        }
      } else {
        delete config.proxy
      }

      const env = merged()
      if (Object.keys(env).length > 0) config.defaults = { ...obj(config.defaults), env }
      else if (config.defaults) delete (config.defaults as Obj).env

      await onSave(service.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <TextField label="Description" value={description} onChange={setDescription} />
      <Field label="Runs">
        <span className="text-sm font-mono text-[var(--muted)]">{runnerLabel(runner)} &middot; </span>
        <input
          value={runProgram}
          onChange={(e) => setRunProgram(e.target.value)}
          className="w-56 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
        />
      </Field>
      <TextField label="Port" value={port} onChange={setPort} width="w-32" mono placeholder="9001" />
      <TextField
        label="Port env"
        value={portEnv}
        onChange={setPortEnv}
        width="w-64"
        mono
        placeholder="(only if the program reads a custom var)"
      />
      <TextField label="Health path" value={health} onChange={setHealth} width="w-48" mono placeholder="/health" />
      <TextField label="Proxy path" value={proxyPath} onChange={setProxyPath} width="w-48" mono placeholder="/my-service" />
      <TextField label="Proxy host" value={proxyHost} onChange={setProxyHost} mono placeholder="my-service.lan" />
      {envEditor}
      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(service.id) : undefined}
        deleteLabel="Remove service"
      />
    </div>
  )
}
