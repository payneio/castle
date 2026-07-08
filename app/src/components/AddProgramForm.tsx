import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { X, Folder, ArrowUp, Check, GitBranch } from "lucide-react"
import { useBrowse, useAdoptProgram } from "@/services/api/hooks"
import { TextField } from "./detail/fields"

const IS_GIT_URL = /^(https?:\/\/|git@|ssh:\/\/)|\.git$/

/** Split the typed path into the directory to browse and the trailing partial
 * segment to filter by — the autocomplete engine. Typing within a directory only
 * changes the filter (client-side, no refetch); crossing a "/" browses the new dir.
 *   "/data/repos/wid" -> browse "/data/repos", filter "wid"
 *   "/data/repos/"    -> browse "/data/repos", filter ""
 *   "wid"             -> browse the default repos dir, filter "wid" */
function splitPath(raw: string): { dir: string | null; filter: string } {
  if (raw === "") return { dir: null, filter: "" }
  if (raw.endsWith("/")) return { dir: raw.length > 1 ? raw.slice(0, -1) : "/", filter: "" }
  const idx = raw.lastIndexOf("/")
  if (idx === -1) return { dir: null, filter: raw }
  if (idx === 0) return { dir: "/", filter: raw.slice(1) }
  return { dir: raw.slice(0, idx), filter: raw.slice(idx + 1) }
}

/** Adopt an existing repo as a program (the web `castle program add`). Programs
 * live on the *server's* filesystem, so the picker browses the server's dirs: type
 * a path (autocompletes as you go), navigate the listing, or paste a git URL. */
export function AddProgramForm({
  existingNames,
  onCancel,
}: {
  existingNames: string[]
  onCancel: () => void
}) {
  const navigate = useNavigate()
  const adopt = useAdoptProgram()

  // The path bar is the single source of truth — its value is the adopt target.
  // Empty browses the server's repos dir (surfaced as the placeholder), so the
  // listing is populated from the first render without seeding the field.
  const [input, setInput] = useState("")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [error, setError] = useState("")

  const target = input.trim()
  const isGit = IS_GIT_URL.test(target)
  const { dir, filter } = splitPath(target)
  const { data: browse, isFetching, error: browseError } = useBrowse(dir, !isGit)

  const entries = (browse?.entries ?? []).filter((e) =>
    filter ? e.name.toLowerCase().startsWith(filter.toLowerCase()) : true,
  )

  const suggestedName = target
    ? target.replace(/\/+$/, "").split("/").pop()!.replace(/\.git$/, "")
    : ""
  const effectiveName = name.trim() || suggestedName
  const nameError =
    name && !/^[a-z0-9][a-z0-9-]*$/.test(name)
      ? "lowercase letters, numbers, hyphens"
      : effectiveName && existingNames.includes(effectiveName)
        ? "already exists"
        : ""

  const submit = async () => {
    if (!target || nameError) return
    setError("")
    try {
      const res = await adopt.mutateAsync({
        target,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
      })
      navigate(`/programs/${res.program}`)
    } catch (e: unknown) {
      let msg = e instanceof Error ? e.message : String(e)
      try {
        msg = JSON.parse((e as Error).message).detail ?? msg
      } catch {
        /* keep msg */
      }
      setError(msg)
    }
  }

  return (
    <div className="bg-[var(--card)] border border-[var(--primary)] rounded-lg p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Add program</h3>
        <button onClick={onCancel} className="text-[var(--muted)] hover:text-[var(--foreground)]">
          <X size={16} />
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-900/20 border border-red-800 rounded px-3 py-1.5">
          {error}
        </div>
      )}

      {/* Editable path bar + live directory listing (or a pasted git URL). */}
      <div className="border border-[var(--border)] rounded">
        <div className="flex items-center gap-2 px-2 py-1.5 border-b border-[var(--border)] bg-black/20">
          <button
            onClick={() => browse?.parent && setInput(browse.parent + "/")}
            disabled={isGit || !browse?.parent}
            title="Up one level"
            className="text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30 shrink-0"
          >
            <ArrowUp size={14} />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            autoFocus
            spellCheck={false}
            placeholder={browse?.path ? `${browse.path}/  (or a git URL)` : "/data/repos/… or a git URL"}
            className="flex-1 min-w-0 bg-transparent text-xs font-mono text-[var(--foreground)] focus:outline-none py-1"
          />
          {isFetching && !isGit && <span className="text-[10px] text-[var(--muted)] shrink-0">…</span>}
        </div>

        {!isGit && (
          <div className="max-h-56 overflow-y-auto">
            {browseError ? (
              <p className="text-xs text-red-400 px-3 py-3">
                {(() => {
                  const m = browseError instanceof Error ? browseError.message : ""
                  try {
                    return JSON.parse(m).detail ?? "Cannot read directory"
                  } catch {
                    return m || "Cannot read directory"
                  }
                })()}
              </p>
            ) : entries.length > 0 ? (
              entries.map((e) => (
                <div
                  key={e.path}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm border-b border-[var(--border)]/50 last:border-0"
                >
                  <button
                    onClick={() => setInput(e.path + "/")}
                    className="flex items-center gap-2 min-w-0 flex-1 text-left hover:text-[var(--primary)]"
                    title="Open"
                  >
                    {e.is_git ? (
                      <GitBranch size={13} className="shrink-0 text-[var(--primary)]" />
                    ) : (
                      <Folder size={13} className="shrink-0 text-[var(--muted)]" />
                    )}
                    <span className="truncate font-mono">{e.name}</span>
                  </button>
                  <button
                    onClick={() => setInput(e.path)}
                    className={`shrink-0 px-2 py-0.5 text-xs rounded border transition-colors ${
                      e.is_program
                        ? "border-[var(--primary)] text-[var(--primary)] hover:bg-[var(--primary)] hover:text-white"
                        : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {target === e.path ? (
                      <span className="flex items-center gap-1">
                        <Check size={11} /> picked
                      </span>
                    ) : (
                      "pick"
                    )}
                  </button>
                </div>
              ))
            ) : (
              <p className="text-xs text-[var(--muted)] px-3 py-3">
                {filter ? "No matching sub-directories." : "No sub-directories."}
              </p>
            )}
          </div>
        )}
      </div>

      {target && (
        <p className="text-xs text-[var(--muted)]">
          Registering <span className="font-mono text-[var(--foreground)]">{target}</span>
          {isGit && " (cloned later via castle clone)"}
        </p>
      )}

      <TextField
        label="Name"
        value={name}
        onChange={(v) => setName(v.toLowerCase())}
        mono
        placeholder={suggestedName || "program-name"}
      />
      {nameError && <p className="text-xs text-red-400 -mt-2 ml-28 sm:ml-36">{nameError}</p>}

      <TextField label="Description" value={description} onChange={setDescription} />

      <div className="flex justify-end gap-2 pt-2">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={!target || !!nameError || adopt.isPending}
          className="px-4 py-1.5 text-sm rounded bg-green-700 hover:bg-green-600 text-white transition-colors disabled:opacity-40"
        >
          {adopt.isPending ? "Registering…" : "Register"}
        </button>
      </div>
    </div>
  )
}
