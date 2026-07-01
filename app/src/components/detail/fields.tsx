import { useMemo, useState } from "react"
import { Trash2 } from "lucide-react"
import { SecretsEditor } from "@/components/SecretsEditor"
import { ConfirmModal } from "@/components/ConfirmModal"

const INPUT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div className="flex items-start gap-4">
      <label className="w-24 sm:w-32 shrink-0 text-sm font-medium pt-1.5">{label}</label>
      <div className="flex-1 min-w-0">
        {children}
        {hint && <p className="text-xs text-[var(--muted)] mt-1 leading-snug">{hint}</p>}
      </div>
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
  hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  mono?: boolean
  width?: string
  hint?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${width ?? "w-full"} ${INPUT} ${mono ? "font-mono" : ""}`}
      />
    </Field>
  )
}

// A value that is *exactly* a secret ref → fully editable via SecretsEditor.
const SECRET_RE = /^\$\{secret:([^}]+)\}$/
// A secret ref embedded anywhere in a value (e.g. `neo4j/${secret:PW}`). These
// are composite literals, so we surface them read-only rather than letting
// merged() rewrite the value and clobber the surrounding text.
const EMBEDDED_SECRET_RE = /\$\{secret:([^}]+)\}/g

/** Hook for editing a run env that mixes plain vars and `${secret:NAME}` refs.
 * Returns the editor element plus a `merged()` that reconstitutes the env. */
export function useEnvSecrets(initial: Record<string, string>) {
  const { plain, secretRefs, embeddedRefs } = useMemo(() => {
    const p: Record<string, string> = {}
    const s: Record<string, string> = {}
    const e: { envKey: string; secretName: string }[] = []
    for (const [k, v] of Object.entries(initial)) {
      const m = SECRET_RE.exec(v)
      if (m) {
        s[k] = m[1]
      } else {
        // Composite values stay in `plain` so their literal text round-trips
        // untouched; any embedded secret names are surfaced read-only below.
        p[k] = v
        for (const em of v.matchAll(EMBEDDED_SECRET_RE)) {
          e.push({ envKey: k, secretName: em[1] })
        }
      }
    }
    return { plain: p, secretRefs: s, embeddedRefs: e }
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
          <p className="text-xs text-[var(--muted)]">
            Use <code className="font-mono">${"{port}"}</code>,{" "}
            <code className="font-mono">${"{data_dir}"}</code>,{" "}
            <code className="font-mono">${"{name}"}</code>,{" "}
            <code className="font-mono">${"{public_url}"}</code> for castle's computed values,
            and <code className="font-mono">${"{secret:NAME}"}</code> for secrets.
          </p>
          {Object.entries(env).map(([key, val]) => (
            <div key={key} className="flex items-center gap-2">
              <input
                value={key}
                readOnly
                className={`w-24 sm:w-56 min-w-0 ${INPUT} text-xs text-[var(--muted)]`}
              />
              <span className="text-[var(--muted)] shrink-0">=</span>
              <input
                value={val}
                onChange={(e) => setEnv((p) => ({ ...p, [key]: e.target.value }))}
                className={`flex-1 min-w-0 ${INPUT} text-xs font-mono`}
              />
              <button
                onClick={() =>
                  setEnv((p) => {
                    const n = { ...p }
                    delete n[key]
                    return n
                  })
                }
                className="text-red-400 hover:text-red-300 p-0.5 shrink-0"
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
        {embeddedRefs.length > 0 && (
          <div className="mt-2 space-y-1">
            {embeddedRefs.map(({ envKey, secretName }) => (
              <p
                key={`${envKey}:${secretName}`}
                className="text-xs font-mono text-[var(--muted)]"
              >
                <span className="text-[var(--foreground)]">{secretName}</span> — embedded in{" "}
                {envKey} (read-only)
              </p>
            ))}
          </div>
        )}
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
  const [confirmOpen, setConfirmOpen] = useState(false)
  return (
    <div className="flex items-center justify-between pt-3 border-t border-[var(--border)]">
      {deleteBlocked ? (
        <span className="text-xs text-amber-400">{deleteBlocked}</span>
      ) : onDelete ? (
        <button
          onClick={() => setConfirmOpen(true)}
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
      {onDelete && (
        <ConfirmModal
          open={confirmOpen}
          title={deleteLabel}
          body={confirmMessage}
          confirmLabel={deleteLabel}
          danger
          onConfirm={() => {
            setConfirmOpen(false)
            onDelete()
          }}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  )
}
