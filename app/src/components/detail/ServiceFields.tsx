import { useState } from "react"
import type { ServiceDetail } from "@/types"
import { useGateway } from "@/services/api/hooks"
import { gatewayHost, publicGatewayHost } from "@/lib/labels"
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
  const { data: gateway } = useGateway()
  const domain = gateway?.domain
  const publicDomain = gateway?.public_domain
  const m = service.manifest
  const run = obj(m.run)
  const internal = obj(obj(obj(m.expose).http).internal)
  const httpExpose = obj(obj(m.expose).http)
  // A raw-TCP service (postgres, redis, …) exposes `expose.tcp`, not `expose.http`.
  // It's reachable at <name>.<domain>:<port> via DNS (no gateway HTTP route), so the
  // HTTP port/health/reach controls below don't apply — show its exposure read-only
  // and never rebuild `expose` on save (that would nuke expose.tcp). Edit TCP/TLS in
  // deployments/<name>.yaml for now.
  const tcp = obj(obj(m.expose).tcp)
  const tcpTls = obj(tcp.tls)
  const isTcp = tcp.port != null

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
  // How far the service reaches: off | internal | public. Falls back to the
  // legacy proxy/public booleans for any deployment not yet re-saved.
  const [reach, setReach] = useState(
    (m.reach as string) ?? (m.public === true ? "public" : m.proxy === true ? "internal" : "off"),
  )

  const { element: envEditor, merged } = useEnvSecrets(obj(obj(m.defaults).env) as Record<string, string>)

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      // The API merges (PATCH): omit = preserve, null = clear. So to CLEAR a field
      // we must send an explicit null, not drop it — otherwise the old value sticks.
      config.description = description || null

      // Rebuild the run block for the chosen launcher, preserving other fields.
      config.run = applyLauncher(obj(config.run), launcher, runProgram)

      // For a TCP service, leave expose.tcp + reach exactly as-is (they're already
      // in the cloned config) — only the HTTP path rebuilds expose from the form.
      if (!isTcp) {
        if (port) {
          config.expose = {
            http: {
              internal: { port: parseInt(port, 10) },
              ...(health ? { health_path: health } : {}),
            },
          }
        } else {
          config.expose = null // explicit clear (merge: omit would preserve the old port)
        }
        // reach needs a port to route through the gateway; without one it's off.
        config.reach = port ? reach : "off"
      }
      delete config.proxy
      delete config.public

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
      {isTcp ? (
        <Field
          label="Exposure"
          hint={`A raw-TCP service — reachable by name + port via DNS, not the HTTP gateway. Edit its port/TLS in deployments/${service.id}.yaml for now.`}
        >
          <div className="font-mono text-xs text-[var(--muted)] space-y-1">
            <div>
              <span className="text-[var(--fg)]">tcp</span> · port{" "}
              <span className="text-[var(--fg)]">{String(tcp.port)}</span>
              {tcpTls.material && tcpTls.material !== "off" ? (
                <>
                  {" "}
                  · tls <span className="text-[var(--fg)]">{String(tcpTls.material)}</span>
                </>
              ) : null}
            </div>
            <div>
              reach{" "}
              <span className="text-[var(--fg)]">{String(m.reach ?? "internal")}</span> —{" "}
              {gatewayHost(service.id, domain)}:{String(tcp.port)}
            </div>
          </div>
        </Field>
      ) : (
        <>
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
            label="Reach"
            hint={`How far this service is exposed. off: host:port only. internal: ${gatewayHost(service.id, domain)} via the gateway. public: also to the internet via the Cloudflare tunnel.`}
          >
            <div className="flex items-center gap-2">
              <select
                value={reach}
                onChange={(e) => setReach(e.target.value)}
                disabled={!port}
                className="bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)] disabled:opacity-50"
              >
                <option value="off">off</option>
                <option value="internal">internal</option>
                <option value="public">public</option>
              </select>
              <span className="font-mono text-[var(--muted)] text-xs">
                {!port
                  ? "set a port to expose"
                  : reach === "off"
                    ? "host:port only"
                    : reach === "public"
                      ? publicGatewayHost(service.id, publicDomain)
                      : gatewayHost(service.id, domain)}
              </span>
            </div>
          </Field>
        </>
      )}
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
