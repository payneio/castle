import { useState } from "react"
import { Link } from "react-router-dom"
import { ExternalLink, Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useSecrets } from "@/services/api/hooks"

interface SecretsEditorProps {
  /** Env var → secret name it references: { ENV_VAR_NAME: "SECRET_NAME" }.
   *  This edits the *wiring* only — a deployment stores `${secret:NAME}`, never the
   *  value. Values live in the backend and are managed on the Secrets page. */
  secrets: Record<string, string>
  onSecretsChange: (secrets: Record<string, string>) => void
}

export function SecretsEditor({ secrets, onSecretsChange }: SecretsEditorProps) {
  const { data: names } = useSecrets()
  const known = new Set(names ?? [])
  const [adding, setAdding] = useState(false)
  const [newEnv, setNewEnv] = useState("")
  const [newSecret, setNewSecret] = useState("")

  const setRef = (envKey: string, secretName: string) =>
    onSecretsChange({ ...secrets, [envKey]: secretName })

  const removeRef = (envKey: string) => {
    const next = { ...secrets }
    delete next[envKey]
    onSecretsChange(next)
  }

  const add = () => {
    if (!newEnv.trim() || !newSecret.trim()) return
    onSecretsChange({ ...secrets, [newEnv.trim()]: newSecret.trim() })
    setNewEnv("")
    setNewSecret("")
    setAdding(false)
  }

  const anyUnset = Object.values(secrets).some((n) => !known.has(n))

  return (
    <div className="space-y-2">
      {Object.entries(secrets).map(([envKey, secretName]) => {
        const isSet = known.has(secretName)
        return (
          <div key={envKey} className="flex items-center gap-2">
            <span
              className="w-24 sm:w-48 shrink-0 truncate font-mono text-xs text-[var(--muted)]"
              title={envKey}
            >
              {envKey}
            </span>
            <span className="shrink-0 text-xs text-[var(--muted)]">→</span>
            <input
              value={secretName}
              onChange={(e) => setRef(envKey, e.target.value)}
              list="all-secret-names"
              placeholder="SECRET_NAME"
              className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
            />
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-0.5 text-[9px]",
                isSet
                  ? "bg-green-900/40 text-green-300"
                  : "bg-amber-900/40 text-amber-300",
              )}
              title={isSet ? "value set in the backend" : "no value set — won't resolve"}
            >
              {isSet ? "set" : "unset"}
            </span>
            <Link
              to="/secrets"
              title="Manage value on the Secrets page"
              className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <ExternalLink size={12} />
            </Link>
            <button
              onClick={() => removeRef(envKey)}
              title="Remove this reference"
              className="p-1 shrink-0 text-red-400 hover:text-red-300"
            >
              <Trash2 size={12} />
            </button>
          </div>
        )
      })}

      <datalist id="all-secret-names">
        {(names ?? []).map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>

      {adding ? (
        <div className="flex items-center gap-2">
          <input
            autoFocus
            placeholder="ENV_VAR"
            value={newEnv}
            onChange={(e) => setNewEnv(e.target.value)}
            className="w-28 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
          />
          <span className="shrink-0 text-xs text-[var(--muted)]">→</span>
          <input
            placeholder="SECRET_NAME"
            list="all-secret-names"
            value={newSecret}
            onChange={(e) => setNewSecret(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
            className="flex-1 min-w-0 rounded border border-[var(--border)] bg-black/30 px-2 py-1 text-xs font-mono focus:border-[var(--primary)] focus:outline-none"
          />
          <button onClick={add} className="text-xs text-[var(--primary)] hover:underline">
            Add
          </button>
          <button onClick={() => setAdding(false)} className="text-xs text-[var(--muted)]">
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          <Plus size={10} className="inline mr-1" />
          Add secret ref
        </button>
      )}

      {anyUnset && (
        <p className="text-[10px] text-amber-400/80">
          Unset refs won't resolve — set their value on the{" "}
          <Link to="/secrets" className="underline">
            Secrets
          </Link>{" "}
          page.
        </p>
      )}
    </div>
  )
}
