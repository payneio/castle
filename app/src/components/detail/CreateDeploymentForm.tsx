import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { X } from "lucide-react"
import { apiClient } from "@/services/api/client"
import { Field, TextField } from "./fields"

const SELECT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

export interface CreatePrefill {
  name?: string
  program?: string
  runTarget?: string
  runner?: string
}

/** Create a service or job in castle.yaml, then deploy (and start, for a
 * service). The UI twin of `castle expose`. Reachable standalone or prefilled
 * from a program page. */
export function CreateDeploymentForm({
  kind,
  prefill,
  existingNames,
  onCancel,
}: {
  kind: "service" | "job"
  prefill?: CreatePrefill
  existingNames: string[]
  onCancel: () => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [name, setName] = useState(prefill?.name ?? "")
  const [program] = useState(prefill?.program ?? "")
  const [description, setDescription] = useState("")
  const [runner, setRunner] = useState(prefill?.runner ?? "python")
  const [runTarget, setRunTarget] = useState(prefill?.runTarget ?? prefill?.name ?? "")
  const [port, setPort] = useState("")
  const [health, setHealth] = useState("/health")
  const [path, setPath] = useState("")
  const [host, setHost] = useState("")
  const [schedule, setSchedule] = useState("0 2 * * *")
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState("")

  const nameError =
    name && !/^[a-z0-9][a-z0-9-]*$/.test(name)
      ? "lowercase letters, numbers, hyphens"
      : existingNames.includes(name)
        ? "already exists"
        : ""

  const buildConfig = (): Record<string, unknown> => {
    const run =
      runner === "command"
        ? { runner: "command", argv: runTarget.split(" ").filter(Boolean) }
        : { runner: "python", program: runTarget || name }
    const base: Record<string, unknown> = {
      ...(program ? { program } : {}),
      ...(description ? { description } : {}),
      run,
      manage: { systemd: {} },
    }
    if (kind === "job") {
      base.schedule = schedule
      return base
    }
    if (port) {
      base.expose = {
        http: {
          internal: { port: parseInt(port, 10) },
          ...(health ? { health_path: health } : {}),
        },
      }
    }
    if (path || host) {
      base.proxy = {
        caddy: {
          ...(path ? { path_prefix: path.startsWith("/") ? path : `/${path}` } : {}),
          ...(host ? { host } : {}),
        },
      }
    }
    return base
  }

  const submit = async () => {
    if (!name || nameError) return
    setError("")
    try {
      setBusy("Saving…")
      await apiClient.put(`/config/${kind}s/${name}`, { config: buildConfig() })
      setBusy("Deploying…")
      await apiClient.post(`/deploy`, { name })
      if (kind === "service") {
        setBusy("Starting…")
        await apiClient.post(`/services/${name}/start`, {})
      }
      qc.invalidateQueries({ queryKey: [`${kind}s`] })
      qc.invalidateQueries({ queryKey: ["programs"] })
      qc.invalidateQueries({ queryKey: ["status"] })
      navigate(kind === "service" ? `/services/${name}` : `/jobs/${name}`)
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
        <h3 className="font-semibold">New {kind}{program ? ` for ${program}` : ""}</h3>
        <button onClick={onCancel} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X size={16} />
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded px-3 py-1.5">
          {error}
        </div>
      )}

      <Field label="Name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          placeholder={kind === "service" ? "my-service" : "my-job"}
          autoFocus
          className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-[var(--primary)]"
        />
        {nameError && <p className="text-xs text-red-400 mt-1">{nameError}</p>}
      </Field>

      <TextField label="Description" value={description} onChange={setDescription} />

      <Field label="Runner">
        <select value={runner} onChange={(e) => setRunner(e.target.value)} className={`w-40 ${SELECT}`}>
          <option value="python">python</option>
          <option value="command">command</option>
        </select>
      </Field>
      <TextField
        label="Runs"
        value={runTarget}
        onChange={setRunTarget}
        mono
        placeholder={runner === "command" ? "my-cmd --flag" : "console-script"}
      />

      {kind === "service" ? (
        <>
          <TextField label="Port" value={port} onChange={setPort} width="w-32" mono placeholder="9001" />
          <TextField label="Health path" value={health} onChange={setHealth} width="w-48" mono />
          <TextField label="Proxy path" value={path} onChange={setPath} width="w-48" mono placeholder={`/${name || "name"}`} />
          <TextField label="Proxy host" value={host} onChange={setHost} mono placeholder="my-service.lan (optional)" />
        </>
      ) : (
        <TextField label="Schedule" value={schedule} onChange={setSchedule} width="w-48" mono placeholder="0 2 * * *" />
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
          {busy ?? `Create ${kind}`}
        </button>
      </div>
    </div>
  )
}
