import { useState } from "react"
import type { ProgramDetail } from "@/types"
import { useStacks } from "@/services/api/hooks"
import { Field, TextField, FormFooter } from "./fields"

const SELECT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

// Verbs the commands editor exposes. `build` lives in `build.commands`; the rest
// in `commands`. A declared command overrides the stack default (or supplies the
// verb when there's no stack).
const VERBS = ["build", "test", "lint", "type-check", "run"]

interface Props {
  program: ProgramDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>

/** Edit a program's catalog config (its source identity), not how it's deployed. */
export function ProgramFields({ program, onSave, onDelete }: Props) {
  const m = program.manifest
  const { data: stacks = [] } = useStacks()
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [description, setDescription] = useState((m.description as string) ?? "")
  const [source, setSource] = useState((m.source as string) ?? "")
  const [stack, setStack] = useState((m.stack as string) ?? "")
  const [version, setVersion] = useState((m.version as string) ?? "")
  const [repo, setRepo] = useState((m.repo as string) ?? "")
  const [ref, setRef] = useState((m.ref as string) ?? "")
  const [deps, setDeps] = useState(((m.system_dependencies as string[]) ?? []).join(", "))

  const readVerb = (verb: string): string => {
    if (verb === "build") {
      const c = (m.build as { commands?: string[][] } | undefined)?.commands
      return (c?.[0] ?? []).join(" ")
    }
    const cmds = (m.commands as Record<string, string[][]> | undefined) ?? {}
    const key = verb === "type-check" && !cmds["type-check"] ? "type_check" : verb
    return (cmds[key]?.[0] ?? []).join(" ")
  }
  const [cmds, setCmds] = useState<Record<string, string>>(() =>
    Object.fromEntries(VERBS.map((v) => [v, readVerb(v)])),
  )

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Obj = { ...m }
      delete config.id
      config.description = description || undefined
      config.source = source || undefined
      config.stack = stack || undefined
      config.version = version || undefined
      config.repo = repo || undefined
      config.ref = ref || undefined
      config.system_dependencies = deps.split(",").map((d) => d.trim()).filter(Boolean)

      const commands: Record<string, string[][]> = {}
      let buildArgv: string[][] | null = null
      for (const v of VERBS) {
        const s = (cmds[v] ?? "").trim()
        if (!s) continue
        const argv: string[][] = [s.split(/\s+/)]
        if (v === "build") buildArgv = argv
        else commands[v] = argv
      }
      if (buildArgv) config.build = { ...((m.build as Obj) ?? {}), commands: buildArgv }
      config.commands = Object.keys(commands).length ? commands : undefined

      await onSave(program.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <TextField
        label="Description"
        value={description}
        onChange={setDescription}
        hint="One-line summary. A service or job running this program inherits it when it has none of its own."
      />
      <TextField
        label="Source"
        value={source}
        onChange={setSource}
        mono
        placeholder="/data/repos/my-prog"
        hint="The working copy on disk. Castle runs dev verbs and builds here. Absolute path, or repo:<name> for castle's own programs."
      />
      <Field
        label="Stack"
        hint="Optional toolchain template — seeds default dev-verb commands and a scaffold for new code. Leave empty and declare commands below to wire in any repo."
      >
        <select value={stack} onChange={(e) => setStack(e.target.value)} className={`w-48 ${SELECT}`}>
          <option value="">(none)</option>
          {/* Options come from the backend (GET /stacks); include the current
              value even if unknown so it never silently blanks. */}
          {Array.from(new Set([...stacks, ...(stack ? [stack] : [])])).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>
      <TextField label="Version" value={version} onChange={setVersion} width="w-32" hint="Optional metadata." />
      <TextField
        label="Repo"
        value={repo}
        onChange={setRepo}
        mono
        placeholder="https://github.com/me/x.git"
        hint="Git URL so 'castle program clone' can fetch the source on a fresh machine. An existing working copy at Source takes precedence."
      />
      <TextField
        label="Ref"
        value={ref}
        onChange={setRef}
        width="w-48"
        placeholder="branch / tag / commit"
        hint="Optional ref to clone (branch, tag, or commit)."
      />
      <TextField
        label="System deps"
        value={deps}
        onChange={setDeps}
        placeholder="pandoc, poppler-utils"
        hint="OS packages the program needs. Listed for reference — castle does not install them."
      />

      <Field
        label="Commands"
        hint="How to build/test/lint/run this program. A declared command overrides the stack default — and is how a program with no stack gets its dev verbs. One argv per line (e.g. ruff check .)."
      >
        <div className="space-y-1.5 pt-1.5">
          {VERBS.map((verb) => (
            <div key={verb} className="flex items-center gap-2">
              <span className="text-xs text-[var(--muted)] w-20 shrink-0 font-mono">{verb}</span>
              <input
                value={cmds[verb] ?? ""}
                onChange={(e) => setCmds((c) => ({ ...c, [verb]: e.target.value }))}
                placeholder={stack ? "(stack default)" : "—"}
                className="flex-1 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
              />
            </div>
          ))}
        </div>
      </Field>

      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(program.id) : undefined}
        deleteLabel="Remove program"
        confirmMessage={`Remove program "${program.id}" from castle.yaml? (Source on disk is untouched.)`}
        deleteBlocked={
          program.services.length + program.jobs.length > 0
            ? "Programs with active jobs or services cannot be removed — delete those first."
            : undefined
        }
      />
    </div>
  )
}
