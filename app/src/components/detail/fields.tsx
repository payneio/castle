import { useMemo, useState } from "react"
import { Trash2 } from "lucide-react"
import { SecretsEditor } from "@/components/SecretsEditor"

const INPUT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4">
      <label className="w-32 shrink-0 text-sm font-medium pt-1.5">{label}</label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  mono,
  width,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  mono?: boolean
  width?: string
}) {
  return (
    <Field label={label}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${width ?? "w-full"} ${INPUT} ${mono ? "font-mono" : ""}`}
      />
    </Field>
  )
}

const SECRET_RE = /^\$\{secret:([^}]+)\}$/

/** Hook for editing a run env that mixes plain vars and `${secret:NAME}` refs.
 * Returns the editor element plus a `merged()` that reconstitutes the env. */
export function useEnvSecrets(initial: Record<string, string>) {
  const { plain, secretRefs } = useMemo(() => {
    const p: Record<string, string> = {}
    const s: Record<string, string> = {}
    for (const [k, v] of Object.entries(initial)) {
      const m = SECRET_RE.exec(v)
      if (m) s[k] = m[1]
      else p[k] = v
    }
    return { plain: p, secretRefs: s }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [env, setEnv] = useState<Record<string, string>>(plain)
  const [secrets, setSecrets] = useState<Record<string, string>>(secretRefs)

  const merged = (): Record<string, string> => {
    const out: Record<string, string> = { ...env }
    for (const [k, name] of Object.entries(secrets)) out[k] = `\${secret:${name}}`
    return out
  }

  const element = (
    <div className="space-y-4">
      <Field label="Environment">
        <div className="space-y-2">
          {Object.entries(env).map(([key, val]) => (
            <div key={key} className="flex items-center gap-2">
              <input value={key} readOnly className={`w-56 ${INPUT} text-xs text-[var(--muted)]`} />
              <span className="text-[var(--muted)]">=</span>
              <input
                value={val}
                onChange={(e) => setEnv((p) => ({ ...p, [key]: e.target.value }))}
                className={`flex-1 ${INPUT} text-xs font-mono`}
              />
              <button
                onClick={() =>
                  setEnv((p) => {
                    const n = { ...p }
                    delete n[key]
                    return n
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
              if (key) setEnv((p) => ({ ...p, [key]: "" }))
            }}
            className="text-xs text-[var(--primary)] hover:underline"
          >
            + Add variable
          </button>
        </div>
      </Field>
      <Field label="Secrets">
        <SecretsEditor secrets={secrets} onSecretsChange={setSecrets} />
      </Field>
    </div>
  )

  return { element, merged }
}

/** Save/Delete footer shared by the typed config forms. */
export function FormFooter({
  saving,
  saved,
  onSave,
  onDelete,
  deleteLabel,
  confirmMessage,
  deleteBlocked,
}: {
  saving: boolean
  saved: boolean
  onSave: () => void
  onDelete?: () => void
  deleteLabel: string
  confirmMessage?: string
  /** When set, removal is disallowed and this reason is shown instead of the button. */
  deleteBlocked?: string
}) {
  return (
    <div className="flex items-center justify-between pt-3 border-t border-[var(--border)]">
      {deleteBlocked ? (
        <span className="text-xs text-amber-400">{deleteBlocked}</span>
      ) : onDelete ? (
        <button
          onClick={() => {
            if (window.confirm(confirmMessage ?? `${deleteLabel}?`)) onDelete()
          }}
          className="flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300"
        >
          <Trash2 size={12} /> {deleteLabel}
        </button>
      ) : (
        <div />
      )}
      <button
        onClick={onSave}
        disabled={saving}
        className="px-3 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 text-white transition-colors disabled:opacity-40"
      >
        {saving ? "Saving…" : saved ? "Saved" : "Save"}
      </button>
    </div>
  )
}
