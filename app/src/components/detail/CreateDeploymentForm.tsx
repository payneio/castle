import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { X } from "lucide-react"
import { apiClient } from "@/services/api/client"
import { useGateway } from "@/services/api/hooks"
import { gatewayHost, publicGatewayHost } from "@/lib/labels"
import { Field, TextField } from "./fields"

const SELECT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

export type DeploymentKind = "service" | "job" | "tool" | "static"

export interface CreatePrefill {
  name?: string
  program?: string
  runTarget?: string
  launcher?: string
}

const KIND_INFO: Record<DeploymentKind, { label: string; hint: string }> = {
  service: { label: "Service", hint: "Long-running process (systemd)" },
  job: { label: "Job", hint: "Scheduled task (systemd timer)" },
  tool: { label: "Tool", hint: "CLI installed on PATH" },
  static: { label: "Static", hint: "Static site served by the gateway" },
}

/** Create a deployment in castle.yaml, then deploy (and start, for a service).
 * A pick-a-kind wizard: the chosen kind sets the manager and shows only its
 * relevant fields. Reachable standalone or prefilled from a program page. */
export function CreateDeploymentForm({
  kind: initialKind,
  prefill,
  existingNames,
  onCancel,
}: {
  kind?: DeploymentKind
  prefill?: CreatePrefill
  existingNames: string[]
  onCancel: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data: gateway } = useGateway()
  const domain = gateway?.domain
  const publicDomain = gateway?.public_domain

  const [kind, setKind] = useState<DeploymentKind>(initialKind ?? "service")
  const [name, setName] = useState(prefill?.name ?? "")
  const [program] = useState(prefill?.program ?? "")
  const [description, setDescription] = useState("")
  const [launcher, setLauncher] = useState(prefill?.launcher ?? "python")
  const [runTarget, setRunTarget] = useState(prefill?.runTarget ?? prefill?.name ?? "")
  const [root, setRoot] = useState("dist")
  const [port, setPort] = useState("")
  const [health, setHealth] = useState("/health")
  const [proxy, setProxy] = useState(true)
  const [isPublic, setIsPublic] = useState(false)
  const [schedule, setSchedule] = useState("0 2 * * *")
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState("")

  const isSystemd = kind === "service" || kind === "job"

  const nameError =
    name && !/^[a-z0-9][a-z0-9-]*$/.test(name)
      ? "lowercase letters, numbers, hyphens"
      : existingNames.includes(name)
        ? "already exists"
        : ""

  const buildRun = () =>
    launcher === "command"
      ? { launcher: "command", argv: runTarget.split(" ").filter(Boolean) }
      : { launcher: "python", program: runTarget || name }

  const buildConfig = (): Record<string, unknown> => {
    const base: Record<string, unknown> = {
      ...(program ? { program } : {}),
      ...(description ? { description } : {}),
    }
    if (kind === "tool") return { ...base, manager: "path" }
    if (kind === "static") return { ...base, manager: "caddy", root }

    // systemd (service or job)
    const cfg: Record<string, unknown> = {
      ...base,
      manager: "systemd",
      run: buildRun(),
      manage: { systemd: {} },
    }
    if (kind === "job") {
      cfg.schedule = schedule
      return cfg
    }
    if (port) {
      cfg.expose = {
        http: {
          internal: { port: parseInt(port, 10) },
          ...(health ? { health_path: health } : {}),
        },
      }
    }
    if (proxy) cfg.proxy = true
    if (proxy && isPublic) cfg.public = true
    return cfg
  }

  const submit = async () => {
    if (!name || nameError) return
    setError("")
    try {
      setBusy("Saving…")
      await apiClient.put(`/config/deployments/${name}`, { config: buildConfig() })
      // Converge: render + activate the new deployment in one step.
      setBusy("Applying…")
      await apiClient.post(`/apply`, { name })
      qc.invalidateQueries({ queryKey: ["services"] })
      qc.invalidateQueries({ queryKey: ["jobs"] })
      qc.invalidateQueries({ queryKey: ["programs"] })
      qc.invalidateQueries({ queryKey: ["status"] })
      if (kind === "service") navigate(`/services/${name}`)
      else if (kind === "job") navigate(`/jobs/${name}`)
      else navigate(`/programs/${program || name}`)
    } catch (e: unknown) {
      let msg = e instanceof Error ? e.message : String(e)
      try {
        msg = JSON.parse((e as Error).message).detail ?? msg
      } catch {
        /* keep msg */
      }
      setError(msg)
      setBusy(null)
    }
  }

  return (
    <div className="bg-[var(--card)] border border-[var(--primary)] rounded-lg p-5 space-y-4 mt-2">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">New deployment{program ? ` for ${program}` : ""}</h3>
        <button onClick={onCancel} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X size={16} />
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded px-3 py-1.5">
          {error}
        </div>
      )}

      {/* Kind picker */}
      <Field label="Kind" hint={KIND_INFO[kind].hint}>
        <div className="flex flex-wrap gap-1.5">
          {(Object.keys(KIND_INFO) as DeploymentKind[]).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={`px-3 py-1 text-sm rounded border transition-colors ${
                kind === k
                  ? "bg-[var(--primary)] text-white border-[var(--primary)]"
                  : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              {KIND_INFO[k].label}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          placeholder="my-deployment"
          autoFocus
          className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
        />
        {nameError && <p className="text-xs text-red-400 mt-1">{nameError}</p>}
      </Field>

      <TextField label="Description" value={description} onChange={setDescription} />

      {/* Program ref — informational; tool/static require it, systemd optional. */}
      {program && (
        <Field label="Program">
          <span className="text-sm font-mono text-[var(--muted)]">{program}</span>
        </Field>
      )}

      {isSystemd && (
        <>
          <Field label="Launcher">
            <select value={launcher} onChange={(e) => setLauncher(e.target.value)} className={`w-40 ${SELECT}`}>
              <option value="python">python</option>
              <option value="command">command</option>
            </select>
          </Field>
          <TextField
            label="Launch"
            value={runTarget}
            onChange={setRunTarget}
            mono
            placeholder={launcher === "command" ? "my-cmd --flag" : "console-script"}
          />
        </>
      )}

      {kind === "service" && (
        <>
          <TextField label="Port" value={port} onChange={setPort} width="w-32" mono placeholder="9001" />
          <TextField label="Health path" value={health} onChange={setHealth} width="w-48" mono />
          <Field label="Expose" hint={`Route through the gateway at ${gatewayHost("<name>", domain)}. Off: reachable only at host:port.`}>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={proxy} onChange={(e) => setProxy(e.target.checked)} />
              <span className="font-mono text-[var(--muted)]">
                {proxy ? gatewayHost(name || "name", domain) : "off (host:port only)"}
              </span>
            </label>
          </Field>
          {proxy && (
            <Field label="Public" hint={`Also publish to the internet via the Cloudflare tunnel at ${publicGatewayHost("<name>", publicDomain)}.`}>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
                <span className="font-mono text-[var(--muted)]">{isPublic ? "public (via tunnel)" : "internal only"}</span>
              </label>
            </Field>
          )}
        </>
      )}

      {kind === "job" && (
        <TextField label="Schedule" value={schedule} onChange={setSchedule} width="w-48" mono placeholder="0 2 * * *" />
      )}

      {kind === "static" && (
        <TextField
          label="Root"
          value={root}
          onChange={setRoot}
          width="w-48"
          mono
          placeholder="dist"
        />
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onCancel} className="px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]">
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={!name || !!nameError || !!busy}
          className="px-4 py-1.5 text-sm rounded bg-green-700 hover:bg-green-600 text-white transition-colors disabled:opacity-40"
        >
          {busy ?? `Create ${KIND_INFO[kind].label.toLowerCase()}`}
        </button>
      </div>
    </div>
  )
}
