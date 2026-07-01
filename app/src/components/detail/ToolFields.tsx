import { useState } from "react"
import type { DeploymentDetail } from "@/types"
import { TextField, FormFooter, useEnvSecrets } from "./fields"

interface Props {
  tool: DeploymentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v as Obj) ?? {}

/** Edit a tool's (path) deployment config. A path deployment has no launcher,
 * port, or schedule — only a description and env, plus its manager. */
export function ToolFields({ tool, onSave, onDelete }: Props) {
  const m = tool.manifest
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [description, setDescription] = useState((m.description as string) ?? "")
  const { element: envEditor, merged } = useEnvSecrets(
    obj(obj(m.defaults).env) as Record<string, string>,
  )

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      config.description = description || undefined
      const env = merged()
      if (Object.keys(env).length > 0) config.defaults = { ...obj(config.defaults), env }
      else if (config.defaults) delete (config.defaults as Obj).env
      await onSave(tool.id, config)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <TextField label="Description" value={description} onChange={setDescription} />
      {envEditor}
      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(tool.id) : undefined}
        deleteLabel="Remove tool deployment"
        confirmMessage={`Remove the tool deployment "${tool.id}"? It will be uninstalled from PATH on the next deploy. (The program stays.)`}
      />
    </div>
  )
}
