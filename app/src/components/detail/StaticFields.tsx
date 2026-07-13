import { useState } from "react"
import type { DeploymentDetail } from "@/types"
import { useGateway } from "@/services/api/hooks"
import { gatewayHost, publicGatewayHost } from "@/lib/labels"
import { Field, TextField, FormFooter, PublicHostRadios, useEnvSecrets, useRequires } from "./fields"
import type { Requirement } from "./fields"

interface Props {
  static_: DeploymentDetail
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onDelete?: (name: string) => Promise<void>
}

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v as Obj) ?? {}

/** Edit a static (caddy) deployment: the built dir it serves (`root`), whether it's
 * also public (via the tunnel), a description, and env. No launcher/port/schedule. */
export function StaticFields({ static_: dep, onSave, onDelete }: Props) {
  const { data: gateway } = useGateway()
  const domain = gateway?.domain
  const publicDomain = gateway?.public_domain
  const m = dep.manifest
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [description, setDescription] = useState((m.description as string) ?? "")
  const [root, setRoot] = useState((m.root as string) ?? "dist")
  // Static sites are always served (reach internal|public); the toggle picks public.
  const [isPublic, setIsPublic] = useState(
    ((m.reach as string) ?? (m.public === true ? "public" : "internal")) === "public",
  )
  // Optional exact public FQDN (apex or another zone) overriding <name>.<public_domain>.
  const [publicHost, setPublicHost] = useState((m.public_host as string) ?? "")
  const [publicMode, setPublicMode] = useState<"default" | "custom">(
    m.public_host ? "custom" : "default",
  )
  const { element: envEditor, merged } = useEnvSecrets(
    obj(obj(m.defaults).env) as Record<string, string>,
  )
  const { element: requiresEditor, value: requiresValue } = useRequires(
    (m.requires as Requirement[]) ?? [],
  )

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const config: Record<string, unknown> = JSON.parse(JSON.stringify(m))
      delete config.id
      // Merge (PATCH) semantics: null clears, omit preserves — send null to clear.
      config.description = description || null
      config.root = root || "dist"
      config.reach = isPublic ? "public" : "internal"
      // public_host only applies to a public site using a custom domain; else clear
      // (null) so the merge drops any stale override.
      config.public_host =
        isPublic && publicMode === "custom" && publicHost.trim() ? publicHost.trim() : null
      delete config.public
      config.requires = requiresValue()
      const env = merged()
      if (Object.keys(env).length > 0) config.defaults = { ...obj(config.defaults), env }
      else if (config.defaults) delete (config.defaults as Obj).env
      await onSave(dep.id, config)
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
        label="Root"
        value={root}
        onChange={setRoot}
        mono
        width="w-48"
        placeholder="dist"
        hint="The built directory the gateway serves, relative to the program source (e.g. dist, public)."
      />
      <Field
        label="Reach"
        hint="How far this static site is served. internal: via the gateway. public: also to the internet via the Cloudflare tunnel. (A static site is always served, so there's no 'off'.)"
      >
        <div className="flex items-center gap-1.5">
          <select
            value={isPublic ? "public" : "internal"}
            onChange={(e) => setIsPublic(e.target.value === "public")}
            className="bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
          >
            <option value="internal">internal</option>
            <option value="public">public</option>
          </select>
        </div>
      </Field>
      <Field label="Address" hint="Where this site is reachable.">
        {isPublic ? (
          <PublicHostRadios
            mode={publicMode}
            onModeChange={setPublicMode}
            value={publicHost}
            onChange={setPublicHost}
            defaultHost={publicGatewayHost(dep.id, publicDomain)}
          />
        ) : (
          <span className="font-mono text-xs text-[var(--muted)]">{gatewayHost(dep.id, domain)}</span>
        )}
      </Field>
      {requiresEditor}
      {envEditor}
      <FormFooter
        saving={saving}
        saved={saved}
        onSave={handleSave}
        onDelete={onDelete ? () => onDelete(dep.id) : undefined}
        deleteLabel="Remove static deployment"
        confirmMessage={`Remove the static deployment "${dep.id}"? Its gateway route is dropped on the next deploy. (The program stays.)`}
      />
    </div>
  )
}
