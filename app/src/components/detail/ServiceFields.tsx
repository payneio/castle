import { useState } from "react"
import type { ServiceDetail } from "@/types"
import { Field, TextField, FormFooter, useEnvSecrets } from "./fields"

interface Props {
  service: ServiceDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v as Obj) ?? {}

// The systemd launch mechanisms (a service is manager=systemd). Editable, so a
// mis-set launcher can be corrected; the primary "Launch" target maps per launcher.
const LAUNCHERS = ["python", "command", "container", "compose", "node"]

/** Fold the "Launch" text into the run block for the chosen launcher, preserving
 * any other run fields (args, ports, package_manager, …) already present. */
function applyLauncher(run: Obj, launcher: string, target: string): Obj {
  const out: Obj = { ...run, launcher }
  const t = target.trim()
  if (launcher === "command") {
    out.argv = t.split(/\s+/).filter(Boolean)
    delete out.program
  } else if (launcher === "python") {
    out.program = t
    delete out.argv
  } else if (launcher === "container") {
    if (t) out.image = t
  } else if (launcher === "node") {
    if (t) out.script = t
  } else if (launcher === "compose") {
    if (t) out.file = t
  }
  return out
}

/** Edit a service's deployment config (run / expose / proxy / env). */
export function ServiceFields({ service, onSave, onDelete }: Props) {
  const m = service.manifest
  const run = obj(m.run)
  const internal = obj(obj(obj(m.expose).http).internal)
  const httpExpose = obj(obj(m.expose).http)

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [description, setDescription] = useState((m.description as string) ?? "")
  const [launcher, setLauncher] = useState((run.launcher as string) ?? "python")
  const [runProgram, setRunProgram] = useState(
    (run.program as string) ||
      ((run.argv as string[]) ?? []).join(" ") ||
      (run.image as string) ||
      (run.script as string) ||
      (run.file as string) ||
      "",
  )
  const [port, setPort] = useState(internal.port != null ? String(internal.port) : "")
  const [health, setHealth] = useState((httpExpose.health_path as string) ?? "")
  // Exposed at <service-name>.<gateway.domain> when proxy is true.
  const [expose, setExpose] = useState(m.proxy === true)

  const { element: envEditor, merged } = useEnvSecrets(obj(obj(m.defaults).env) as Record<string, string>)

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      config.description = description || undefined

      // Rebuild the run block for the chosen launcher, preserving other fields.
      config.run = applyLauncher(obj(config.run), launcher, runProgram)

      if (port) {
        config.expose = {
          http: {
            internal: { port: parseInt(port, 10) },
            ...(health ? { health_path: health } : {}),
          },
        }
      } else {
        delete config.expose
      }

      if (expose) config.proxy = true
      else delete config.proxy

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
      <Field
        label="Launch"
        hint="How this service starts: the launcher, and its target — a console script (python), a command/argv (command), an image (container), a script (node), or a compose file (compose)."
      >
        <div className="flex items-center gap-2">
          <select
            value={launcher}
            onChange={(e) => setLauncher(e.target.value)}
            className="bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
          >
            {LAUNCHERS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <span className="text-[var(--muted)]">&middot;</span>
          <input
            value={runProgram}
            onChange={(e) => setRunProgram(e.target.value)}
            className="w-full sm:w-56 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
          />
        </div>
      </Field>
      <TextField
        label="Port"
        value={port}
        onChange={setPort}
        width="w-32"
        mono
        placeholder="9001"
        hint="The port the service listens on. Castle health-checks and proxies this port; map it to the program's own var with ${port} in Environment."
      />
      <TextField
        label="Health path"
        value={health}
        onChange={setHealth}
        width="w-48"
        mono
        placeholder="/health"
        hint="HTTP path castle polls to report up/down."
      />
      <Field
        label="Expose"
        hint="Route this service through the gateway at <service-name>.<gateway.domain>. Unchecked: reachable only at its own host:port."
      >
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={expose}
            onChange={(e) => setExpose(e.target.checked)}
          />
          <span className="font-mono text-[var(--muted)]">
            {expose ? `${service.id}.<gateway.domain>` : "off (host:port only)"}
          </span>
        </label>
      </Field>
      {envEditor}
      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(service.id) : undefined}
        deleteLabel="Remove service"
        confirmMessage={`Remove service "${service.id}" from castle.yaml? Run a deploy afterward to tear down its unit.`}
      />
    </div>
  )
}
