import { useState } from "react"
import { Loader2 } from "lucide-react"
import type { DeploymentDetail } from "@/types"
import { apiClient, ApiError } from "@/services/api/client"
import { Field, TextField, FormFooter } from "./fields"

type GenKind = "help" | "deep" | "ai"

interface Props {
  tool: DeploymentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

/** Edit a tool's (path) deployment config. A path deployment has no launcher,
 * port, or schedule — only a description and its `tool_schema` (the neutral
 * tool-call definition handed to agents), plus its manager. It has no run env:
 * a tool is a CLI on PATH, invoked from a shell with castle out of the loop, so
 * `defaults.env` is never applied (deploy.py only wires env for systemd units). */
export function ToolFields({ tool, onSave, onDelete }: Props) {
  const m = tool.manifest
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [description, setDescription] = useState((m.description as string) ?? "")
  const [schemaText, setSchemaText] = useState(
    m.tool_schema ? JSON.stringify(m.tool_schema, null, 2) : "",
  )
  const [schemaError, setSchemaError] = useState<string | null>(null)
  // Which generate action is in-flight (null = idle) — lets each button show its
  // own spinner/label rather than all three reacting to one shared flag.
  const [genKind, setGenKind] = useState<GenKind | null>(null)
  const generating = genKind !== null
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState<{ ok: boolean; msg: string } | null>(null)

  const validate = async () => {
    setValidation(null)
    setSchemaError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(schemaText)
    } catch (e) {
      setValidation({ ok: false, msg: `Invalid JSON: ${e instanceof Error ? e.message : String(e)}` })
      return
    }
    setValidating(true)
    try {
      const res = await apiClient.post<{ valid: boolean; errors: string[] }>(
        "/config/tools/schema/validate",
        parsed,
      )
      setValidation(
        res.valid
          ? { ok: true, msg: "Schema is valid." }
          : { ok: false, msg: res.errors.join(" · ") },
      )
    } catch (e) {
      setValidation({ ok: false, msg: e instanceof ApiError ? e.message : String(e) })
    } finally {
      setValidating(false)
    }
  }

  const generate = async (kind: GenKind) => {
    setGenKind(kind)
    setSchemaError(null)
    setValidation(null)
    try {
      const params = new URLSearchParams()
      if (kind === "deep") params.set("deep", "true")
      if (kind === "ai") params.set("assist", "llm")
      const qs = params.toString()
      const res = await apiClient.post<{ schema: unknown }>(
        `/config/tools/${tool.id}/schema${qs ? `?${qs}` : ""}`,
      )
      setSchemaText(JSON.stringify(res.schema, null, 2))
    } catch (e) {
      setSchemaError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setGenKind(null)
    }
  }

  const handleSave = async () => {
    // Validate the (optional) tool_schema JSON before saving.
    let parsedSchema: unknown = undefined
    if (schemaText.trim()) {
      try {
        parsedSchema = JSON.parse(schemaText)
      } catch (e) {
        setSchemaError(`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`)
        return
      }
    }
    setSchemaError(null)
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      config.description = description || undefined
      config.tool_schema = parsedSchema ?? null // null clears (PATCH semantics)
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
      <Field
        label="Tool schema"
        hint="Neutral tool-call definition ({name, description, parameters}) handed to agents — rendered to OpenAI or Anthropic on read. Generate it from the tool's --help, then edit freely. Leave empty for none."
      >
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <button
              onClick={() => generate("help")}
              disabled={generating}
              className="px-2.5 py-1 text-xs rounded border border-[var(--border)] hover:bg-white/5 transition-colors disabled:opacity-40"
            >
              {genKind === "help" ? "Generating…" : "Generate from --help"}
            </button>
            <button
              onClick={() => generate("deep")}
              disabled={generating}
              className="px-2.5 py-1 text-xs rounded border border-[var(--border)] hover:bg-white/5 transition-colors disabled:opacity-40"
              title="Also walk subcommands"
            >
              Deep
            </button>
            <button
              onClick={() => generate("ai")}
              disabled={generating}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded border border-[var(--border)] hover:bg-white/5 transition-colors disabled:opacity-40"
              title="Use the LLM to structure subcommand trees the parser can't (requires LLM assist enabled)"
            >
              {genKind === "ai" ? (
                <>
                  <Loader2 size={12} className="animate-spin" /> Generating…
                </>
              ) : (
                <>✨ Generate with AI</>
              )}
            </button>
            <button
              onClick={validate}
              disabled={validating || generating || !schemaText.trim()}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded border border-[var(--border)] hover:bg-white/5 transition-colors disabled:opacity-40"
              title="Deterministically check the schema in the box is a valid tool-call definition"
            >
              {validating ? (
                <>
                  <Loader2 size={12} className="animate-spin" /> Validating…
                </>
              ) : (
                "Validate"
              )}
            </button>
            {schemaText && (
              <button
                onClick={() => {
                  setSchemaText("")
                  setSchemaError(null)
                  setValidation(null)
                }}
                className="text-xs text-red-400 hover:text-red-300"
              >
                Clear
              </button>
            )}
          </div>
          <textarea
            value={schemaText}
            onChange={(e) => {
              setSchemaText(e.target.value)
              setValidation(null)
            }}
            spellCheck={false}
            rows={schemaText ? 12 : 3}
            placeholder="{ }  — generate from --help, or paste an Anthropic tool definition"
            className="w-full bg-black/30 border border-[var(--border)] rounded px-3 py-2 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
          />
          {validation && (
            <p className={`text-xs ${validation.ok ? "text-green-400" : "text-amber-400"}`}>
              {validation.ok ? "✓ " : "✗ "}
              {validation.msg}
            </p>
          )}
          {schemaError && <p className="text-xs text-red-400">{schemaError}</p>}
        </div>
      </Field>
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
