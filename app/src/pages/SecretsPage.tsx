import { useState } from "react"
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  Plus,
  Save,
  Server,
  Trash2,
} from "lucide-react"
import { PageHeader } from "@/components/PageHeader"
import { apiClient } from "@/services/api/client"
import {
  useDeleteOverride,
  useDeleteSecret,
  useSecretOverrides,
  useSecrets,
  useSecretsInfo,
  useSetOverride,
  useSetSecret,
} from "@/services/api/hooks"

async function writeClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* fall through */
    }
  }
  try {
    const ta = document.createElement("textarea")
    ta.value = text
    ta.style.position = "fixed"
    ta.style.opacity = "0"
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand("copy")
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export function SecretsPage() {
  const { data: info } = useSecretsInfo()
  const { data: names, isLoading } = useSecrets()
  const { data: overridesResp } = useSecretOverrides()
  const writable = info?.writable ?? false
  const overrides = overridesResp?.overrides ?? {}

  // name -> [nodes that override it], for the per-secret badge.
  const overriddenBy: Record<string, string[]> = {}
  for (const [node, secretNames] of Object.entries(overrides)) {
    for (const n of secretNames) (overriddenBy[n] ??= []).push(node)
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <PageHeader title="Secrets" subtitle="Credentials resolved for services and jobs" />

      {info && (
        <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-[var(--border)] bg-black/20 px-3 py-2 text-xs">
          <span className="inline-flex items-center gap-1.5 font-medium">
            <KeyRound size={13} className="text-[var(--primary)]" />
            backend: <span className="font-mono">{info.backend}</span>
          </span>
          {info.addr && <span className="font-mono text-[var(--muted)]">{info.addr}</span>}
          <span className="text-[var(--muted)]">role: {info.role}</span>
          {!writable && (
            <span className="inline-flex items-center gap-1 text-amber-400">
              <Lock size={12} /> read-only (write on the authority node)
            </span>
          )}
        </div>
      )}

      {writable && <AddSecret />}

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading…</p>
      ) : !names?.length ? (
        <p className="text-[var(--muted)] text-sm">No secrets.</p>
      ) : (
        <div className="mt-2 divide-y divide-[var(--border)] rounded border border-[var(--border)]">
          {names.map((name) => (
            <SecretRow
              key={name}
              name={name}
              writable={writable}
              overriddenOn={overriddenBy[name] ?? []}
            />
          ))}
        </div>
      )}

      <NodeOverrides overrides={overrides} writable={writable} secretNames={names ?? []} />
    </div>
  )
}

function SecretRow({
  name,
  writable,
  overriddenOn = [],
}: {
  name: string
  writable: boolean
  overriddenOn?: string[]
}) {
  const [value, setValue] = useState<string | null>(null)
  const [visible, setVisible] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(false)
  const setSecret = useSetSecret()
  const delSecret = useDeleteSecret()

  const reveal = async () => {
    if (value === null && !loading) {
      setLoading(true)
      try {
        const data = await apiClient.get<{ value: string }>(`/secrets/${name}`)
        setValue(data.value)
      } catch {
        setValue("")
      } finally {
        setLoading(false)
      }
    }
    setVisible((v) => !v)
  }

  const copy = async () => {
    let v = value
    if (v === null) {
      const data = await apiClient.get<{ value: string }>(`/secrets/${name}`).catch(() => null)
      v = data?.value ?? ""
      setValue(v)
    }
    if (await writeClipboard(v)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <span className="w-40 sm:w-64 shrink-0 truncate font-mono text-xs" title={name}>
        {name}
        {overriddenOn.length > 0 && (
          <span
            className="ml-1.5 rounded bg-amber-900/40 px-1 text-[9px] text-amber-300"
            title={`Overridden on: ${overriddenOn.join(", ")}`}
          >
            override: {overriddenOn.join(", ")}
          </span>
        )}
      </span>
      <input
        type={visible ? "text" : "password"}
        value={value ?? "••••••••"}
        readOnly={!writable || value === null}
        placeholder={loading ? "loading…" : "••••••••"}
        onChange={(e) => {
          setValue(e.target.value)
          setDirty(true)
        }}
        className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <button onClick={reveal} className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]" title="Reveal">
        {visible ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
      <button onClick={copy} className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]" title="Copy">
        {copied ? <Check size={13} className="text-green-400" /> : <Copy size={13} />}
      </button>
      {writable && (
        <>
          <button
            onClick={() => {
              if (value !== null && dirty)
                setSecret.mutate({ name, value }, { onSuccess: () => setDirty(false) })
            }}
            disabled={!dirty || setSecret.isPending}
            className="p-1 shrink-0 text-blue-400 hover:text-blue-300 disabled:opacity-30"
            title="Save"
          >
            {setSecret.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          </button>
          <button
            onClick={() => {
              if (confirm(`Delete secret "${name}"?`)) delSecret.mutate(name)
            }}
            className="p-1 shrink-0 text-red-400 hover:text-red-300"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </>
      )}
    </div>
  )
}

function AddSecret() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [value, setValue] = useState("")
  const setSecret = useSetSecret()

  const submit = () => {
    if (!name.trim() || !value) return
    setSecret.mutate(
      { name: name.trim(), value },
      {
        onSuccess: () => {
          setName("")
          setValue("")
          setOpen(false)
        },
      },
    )
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mb-3 text-xs text-[var(--primary)] hover:underline">
        <Plus size={11} className="inline mr-1" />
        Add secret
      </button>
    )
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded border border-[var(--border)] bg-black/20 p-2">
      <input
        autoFocus
        placeholder="NAME"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-40 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <input
        placeholder="value"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <button onClick={submit} disabled={setSecret.isPending} className="rounded bg-[var(--primary)] px-2 py-1 text-xs text-black disabled:opacity-40">
        {setSecret.isPending ? "…" : "Add"}
      </button>
      <button onClick={() => setOpen(false)} className="px-2 py-1 text-xs text-[var(--muted)]">
        Cancel
      </button>
    </div>
  )
}

function NodeOverrides({
  overrides,
  writable,
  secretNames,
}: {
  overrides: Record<string, string[]>
  writable: boolean
  secretNames: string[]
}) {
  const entries = Object.entries(overrides).flatMap(([node, names]) =>
    names.map((name) => ({ node, name })),
  )

  return (
    <div className="mt-8">
      <div className="mb-2 flex items-center gap-2">
        <Server size={14} className="text-[var(--primary)]" />
        <h2 className="text-sm font-semibold">Node overrides</h2>
        <span className="text-xs text-[var(--muted)]">
          per-node values (e.g. a node's own postgres password); shadow the shared secret on that node
        </span>
      </div>

      {writable && <AddOverride secretNames={secretNames} />}

      {entries.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No overrides.</p>
      ) : (
        <div className="divide-y divide-[var(--border)] rounded border border-[var(--border)]">
          {entries.map(({ node, name }) => (
            <OverrideRow key={`${node}/${name}`} node={node} name={name} writable={writable} />
          ))}
        </div>
      )}
    </div>
  )
}

function OverrideRow({ node, name, writable }: { node: string; name: string; writable: boolean }) {
  const [value, setValue] = useState<string | null>(null)
  const [visible, setVisible] = useState(false)
  const [dirty, setDirty] = useState(false)
  const setOverride = useSetOverride()
  const delOverride = useDeleteOverride()

  const reveal = async () => {
    if (value === null) {
      const data = await apiClient
        .get<{ value: string }>(`/secrets/overrides/${node}/${name}`)
        .catch(() => null)
      setValue(data?.value ?? "")
    }
    setVisible((v) => !v)
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <span className="w-24 sm:w-36 shrink-0 truncate font-mono text-xs text-amber-300" title={node}>
        {node}
      </span>
      <span className="w-32 sm:w-52 shrink-0 truncate font-mono text-xs" title={name}>
        {name}
      </span>
      <input
        type={visible ? "text" : "password"}
        value={value ?? "••••••••"}
        readOnly={!writable || value === null}
        onChange={(e) => {
          setValue(e.target.value)
          setDirty(true)
        }}
        className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <button onClick={reveal} className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]" title="Reveal">
        {visible ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
      {writable && (
        <>
          <button
            onClick={() => {
              if (value !== null && dirty)
                setOverride.mutate({ node, name, value }, { onSuccess: () => setDirty(false) })
            }}
            disabled={!dirty || setOverride.isPending}
            className="p-1 shrink-0 text-blue-400 hover:text-blue-300 disabled:opacity-30"
            title="Save"
          >
            {setOverride.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          </button>
          <button
            onClick={() => {
              if (confirm(`Delete override "${name}" for ${node}?`))
                delOverride.mutate({ node, name })
            }}
            className="p-1 shrink-0 text-red-400 hover:text-red-300"
            title="Delete override"
          >
            <Trash2 size={13} />
          </button>
        </>
      )}
    </div>
  )
}

function AddOverride({ secretNames }: { secretNames: string[] }) {
  const [open, setOpen] = useState(false)
  const [node, setNode] = useState("")
  const [name, setName] = useState("")
  const [value, setValue] = useState("")
  const setOverride = useSetOverride()

  const submit = () => {
    if (!node.trim() || !name.trim() || !value) return
    setOverride.mutate(
      { node: node.trim(), name: name.trim(), value },
      {
        onSuccess: () => {
          setNode("")
          setName("")
          setValue("")
          setOpen(false)
        },
      },
    )
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mb-2 text-xs text-[var(--primary)] hover:underline">
        <Plus size={11} className="inline mr-1" />
        Add override
      </button>
    )
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded border border-[var(--border)] bg-black/20 p-2">
      <input
        autoFocus
        placeholder="node (host)"
        value={node}
        onChange={(e) => setNode(e.target.value)}
        className="w-32 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <input
        placeholder="SECRET_NAME"
        list="secret-names"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-44 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <datalist id="secret-names">
        {secretNames.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <input
        placeholder="value"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
      />
      <button onClick={submit} disabled={setOverride.isPending} className="rounded bg-[var(--primary)] px-2 py-1 text-xs text-black disabled:opacity-40">
        {setOverride.isPending ? "…" : "Add"}
      </button>
      <button onClick={() => setOpen(false)} className="px-2 py-1 text-xs text-[var(--muted)]">
        Cancel
      </button>
    </div>
  )
}
