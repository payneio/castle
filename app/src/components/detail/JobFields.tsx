import { useState } from "react"
import type { JobDetail } from "@/types"
import { runnerLabel } from "@/lib/labels"
import { Field, TextField, FormFooter, useEnvSecrets } from "./fields"

interface Props {
  job: JobDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v as Obj) ?? {}

/** Edit a job's deployment config (schedule / run / env). */
export function JobFields({ job, onSave, onDelete }: Props) {
  const m = job.manifest
  const run = obj(m.run)

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [description, setDescription] = useState((m.description as string) ?? "")
  const [schedule, setSchedule] = useState((m.schedule as string) ?? "")
  const [runTarget, setRunTarget] = useState(
    (run.program as string) ?? ((run.argv as string[]) ?? []).join(" "),
  )

  const { element: envEditor, merged } = useEnvSecrets(obj(obj(m.defaults).env) as Record<string, string>)
  const runner = (run.runner as string) ?? "?"

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      config.description = description || undefined
      config.schedule = schedule || undefined

      const runOut = obj(config.run)
      if (runner === "command") runOut.argv = runTarget.split(" ").filter(Boolean)
      else if (runner === "python") runOut.program = runTarget
      config.run = runOut

      const env = merged()
      if (Object.keys(env).length > 0) config.defaults = { ...obj(config.defaults), env }
      else if (config.defaults) delete (config.defaults as Obj).env

      await onSave(job.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <TextField label="Description" value={description} onChange={setDescription} />
      <TextField
        label="Schedule"
        value={schedule}
        onChange={setSchedule}
        width="w-48"
        mono
        placeholder="0 2 * * *"
        hint="Cron expression — castle generates a systemd timer that runs the job on this schedule."
      />
      <Field label="Runs" hint="The console script or command the job runs on each tick, then exits.">
        <span className="text-sm font-mono text-[var(--muted)]">{runnerLabel(runner)} &middot; </span>
        <input
          value={runTarget}
          onChange={(e) => setRunTarget(e.target.value)}
          className="w-56 bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
        />
      </Field>
      {envEditor}
      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(job.id) : undefined}
        deleteLabel="Remove job"
        confirmMessage={`Remove job "${job.id}" from castle.yaml? Run a deploy afterward to tear down its timer.`}
      />
    </div>
  )
}
