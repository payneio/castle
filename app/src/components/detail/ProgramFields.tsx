import { useState } from "react"
import type { ProgramDetail } from "@/types"
import { Field, TextField, FormFooter } from "./fields"

const SELECT =
  "bg-black/30 border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--primary)]"

interface Props {
  program: ProgramDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

/** Edit a program's catalog config (source identity), not how it's deployed. */
export function ProgramFields({ program, onSave, onDelete }: Props) {
  const m = program.manifest
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [description, setDescription] = useState((m.description as string) ?? "")
  const [source, setSource] = useState((m.source as string) ?? "")
  const [behavior, setBehavior] = useState((m.behavior as string) ?? "")
  const [stack, setStack] = useState((m.stack as string) ?? "")
  const [version, setVersion] = useState((m.version as string) ?? "")
  const [repo, setRepo] = useState((m.repo as string) ?? "")
  const [ref, setRef] = useState((m.ref as string) ?? "")
  const [deps, setDeps] = useState(((m.system_dependencies as string[]) ?? []).join(", "))

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = { ...m }
      delete config.id
      config.description = description || undefined
      config.source = source || undefined
      config.behavior = behavior || undefined
      config.stack = stack || undefined
      config.version = version || undefined
      config.repo = repo || undefined
      config.ref = ref || undefined
      config.system_dependencies = deps
        .split(",")
        .map((d) => d.trim())
        .filter(Boolean)
      await onSave(program.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <TextField label="Description" value={description} onChange={setDescription} />
      <TextField label="Source" value={source} onChange={setSource} mono placeholder="/data/repos/my-prog" />
      <Field label="Behavior">
        <select value={behavior} onChange={(e) => setBehavior(e.target.value)} className={`w-48 ${SELECT}`}>
          <option value="">(none)</option>
          <option value="tool">tool</option>
          <option value="daemon">daemon</option>
          <option value="frontend">frontend</option>
        </select>
      </Field>
      <Field label="Stack">
        <select value={stack} onChange={(e) => setStack(e.target.value)} className={`w-48 ${SELECT}`}>
          <option value="">(none)</option>
          <option value="python-cli">python-cli</option>
          <option value="python-fastapi">python-fastapi</option>
          <option value="react-vite">react-vite</option>
        </select>
      </Field>
      <TextField label="Version" value={version} onChange={setVersion} width="w-32" />
      <TextField label="Repo" value={repo} onChange={setRepo} mono placeholder="https://github.com/me/x.git" />
      <TextField label="Ref" value={ref} onChange={setRef} width="w-48" placeholder="branch / tag / commit" />
      <TextField label="System deps" value={deps} onChange={setDeps} placeholder="pandoc, poppler-utils" />

      {program.commands && Object.keys(program.commands).length > 0 && (
        <Field label="Commands">
          <div className="space-y-1 pt-1.5">
            {Object.entries(program.commands).map(([verb, cmds]) => (
              <div key={verb} className="flex gap-2 text-xs">
                <span className="text-[var(--muted)] w-20 shrink-0">{verb}</span>
                <span className="font-mono break-all">{cmds.map((a) => a.join(" ")).join(" && ")}</span>
              </div>
            ))}
          </div>
        </Field>
      )}

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
