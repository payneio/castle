import { useEffect, useState } from "react"
import { Check, Copy, Eye, EyeOff, Loader2, Plus, Save, Trash2 } from "lucide-react"
import { apiClient } from "@/services/api/client"

interface SecretsEditorProps {
  /** Current secret references: { ENV_VAR_NAME: "SECRET_FILE_NAME" } */
  secrets: Record<string, string>
  onSecretsChange: (secrets: Record<string, string>) => void
}

interface SecretState {
  value: string
  original: string
  visible: boolean
  saving: boolean
  saved: boolean
  loaded: boolean
  copied: boolean
}

/** Copy text to the clipboard, returning whether it succeeded.
 *
 * `navigator.clipboard` only exists in a secure context (HTTPS or
 * localhost). The dashboard is reached over plain HTTP across the LAN
 * (e.g. from a phone), where it's undefined — so fall back to the legacy
 * execCommand path, which works in insecure contexts. */
async function writeClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through to the legacy path below.
    }
  }
  try {
    const ta = document.createElement("textarea")
    ta.value = text
    // Keep it out of view and unfocusable to the page layout.
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

export function SecretsEditor({ secrets, onSecretsChange }: SecretsEditorProps) {
  const [states, setStates] = useState<Record<string, SecretState>>({})

  // Load secret values when the secret list changes
  useEffect(() => {
    for (const [envKey, secretName] of Object.entries(secrets)) {
      if (states[envKey]?.loaded) continue
      setStates((prev) => ({
        ...prev,
        [envKey]: {
          value: "", original: "", visible: false,
          saving: false, saved: false, loaded: false, copied: false,
        },
      }))
      apiClient
        .get<{ value: string }>(`/secrets/${secretName}`)
        .then((data) => {
          setStates((prev) => ({
            ...prev,
            [envKey]: { ...prev[envKey], value: data.value, original: data.value, loaded: true },
          }))
        })
        .catch(() => {
          setStates((prev) => ({
            ...prev,
            [envKey]: { ...prev[envKey], loaded: true },
          }))
        })
    }
  }, [Object.keys(secrets).join(",")])

  const handleSave = async (envKey: string) => {
    const s = states[envKey]
    const secretName = secrets[envKey]
    if (!s || !secretName || s.value === s.original) return

    setStates((prev) => ({ ...prev, [envKey]: { ...prev[envKey], saving: true } }))
    try {
      await apiClient.put(`/secrets/${secretName}`, { value: s.value })
      setStates((prev) => ({
        ...prev,
        [envKey]: { ...prev[envKey], saving: false, saved: true, original: s.value },
      }))
      setTimeout(() => {
        setStates((prev) => ({ ...prev, [envKey]: { ...prev[envKey], saved: false } }))
      }, 2000)
    } catch {
      setStates((prev) => ({ ...prev, [envKey]: { ...prev[envKey], saving: false } }))
    }
  }

  const handleAdd = () => {
    const envKey = prompt("Environment variable name (e.g. MY_API_KEY):")
    if (!envKey) return
    const secretName = prompt("Secret file name (stored in ~/.castle/secrets/):", envKey)
    if (!secretName) return
    onSecretsChange({ ...secrets, [envKey]: secretName })
    setStates((prev) => ({
      ...prev,
      [envKey]: {
        value: "", original: "", visible: true,
        saving: false, saved: false, loaded: true, copied: false,
      },
    }))
  }

  const handleCopy = async (envKey: string) => {
    const s = states[envKey]
    if (!s?.loaded) return
    if (!(await writeClipboard(s.value))) return
    setStates((prev) => ({ ...prev, [envKey]: { ...prev[envKey], copied: true } }))
    setTimeout(() => {
      setStates((prev) => ({ ...prev, [envKey]: { ...prev[envKey], copied: false } }))
    }, 2000)
  }

  const handleRemove = (envKey: string) => {
    const next = { ...secrets }
    delete next[envKey]
    onSecretsChange(next)
    setStates((prev) => {
      const n = { ...prev }
      delete n[envKey]
      return n
    })
  }

  return (
    <div className="space-y-2">
      {Object.entries(secrets).map(([envKey, secretName]) => {
        const s = states[envKey]
        const dirty = s ? s.value !== s.original : false

        return (
          <div key={envKey} className="flex items-center gap-2">
            <span className="w-24 sm:w-56 shrink-0 text-xs font-mono text-[var(--muted)] truncate" title={`${envKey} → ${secretName}`}>
              {envKey}
            </span>
            <div className="flex-1 min-w-0 flex items-center gap-1.5">
              <input
                type={s?.visible ? "text" : "password"}
                value={s?.loaded ? s.value : ""}
                placeholder={s?.loaded ? "(empty)" : "loading..."}
                onChange={(e) =>
                  setStates((prev) => ({
                    ...prev,
                    [envKey]: { ...prev[envKey], value: e.target.value },
                  }))
                }
                className="flex-1 min-w-0 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
              />
              <button
                onClick={() =>
                  setStates((prev) => ({
                    ...prev,
                    [envKey]: { ...prev[envKey], visible: !prev[envKey]?.visible },
                  }))
                }
                className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {s?.visible ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
              <button
                onClick={() => handleCopy(envKey)}
                disabled={!s?.loaded}
                title="Copy secret value"
                className="p-1 shrink-0 text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
              >
                {s?.copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
              </button>
              <button
                onClick={() => handleSave(envKey)}
                disabled={!dirty || s?.saving}
                className="p-1 shrink-0 text-blue-400 hover:text-blue-300 disabled:opacity-30"
              >
                {s?.saving ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : s?.saved ? (
                  <Check size={12} className="text-green-400" />
                ) : (
                  <Save size={12} />
                )}
              </button>
              <button
                onClick={() => handleRemove(envKey)}
                className="p-1 shrink-0 text-red-400 hover:text-red-300"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        )
      })}
      <button onClick={handleAdd} className="text-xs text-[var(--primary)] hover:underline">
        <Plus size={10} className="inline mr-1" />Add secret
      </button>
    </div>
  )
}
