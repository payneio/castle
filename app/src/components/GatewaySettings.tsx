import { useState } from "react"
import { Pencil, Check, X, Cable } from "lucide-react"
import type { GatewayInfo } from "@/types"
import { useSaveGatewayConfig } from "@/services/api/hooks"

/** Editable gateway routing + public-exposure settings (domain / public_domain /
 *  tunnel / tls). Saves to castle.yaml; changes take effect on the next apply. */
export function GatewaySettings({ gateway }: { gateway: GatewayInfo }) {
  const { mutate: save, isPending, data: saved } = useSaveGatewayConfig()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    tls: gateway.tls ?? "",
    domain: gateway.domain ?? "",
    public_domain: gateway.public_domain ?? "",
    tunnel_id: gateway.tunnel_id ?? "",
  })

  const field = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const publicConfigured = !!gateway.public_domain && !!gateway.tunnel_id

  if (editing) {
    return (
      <div className="px-4 py-3 border-b border-[var(--border)] grid gap-2 text-sm bg-black/10">
        <Row label="TLS">
          <select value={form.tls} onChange={field("tls")} className={INPUT}>
            <option value="">off</option>
            <option value="acme">acme</option>
            <option value="internal">internal</option>
          </select>
        </Row>
        <Row label="Domain"><input value={form.domain} onChange={field("domain")} placeholder="civil.payne.io" className={INPUT} /></Row>
        <Row label="Public domain"><input value={form.public_domain} onChange={field("public_domain")} placeholder="domain0.org" className={INPUT} /></Row>
        <Row label="Tunnel ID"><input value={form.tunnel_id} onChange={field("tunnel_id")} placeholder="cloudflared tunnel UUID" className={INPUT} /></Row>
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => save(form, { onSuccess: () => setEditing(false) })}
            disabled={isPending}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-[var(--primary)] text-white disabled:opacity-40"
          >
            <Check size={12} /> Save
          </button>
          <button onClick={() => setEditing(false)} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-[var(--border)] text-[var(--muted)]">
            <X size={12} /> Cancel
          </button>
          <span className="text-xs text-[var(--muted)]">Run <span className="font-mono">castle apply</span> (or the Apply button) to converge.</span>
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-2.5 border-b border-[var(--border)] flex items-center gap-x-6 gap-y-1 flex-wrap text-sm">
      <span className="text-[var(--muted)]">
        TLS <span className="text-[var(--foreground)] font-mono">{gateway.tls ?? "off"}</span>
      </span>
      <span className="text-[var(--muted)]">
        Domain <span className="text-[var(--foreground)] font-mono">{gateway.domain ?? "—"}</span>
      </span>
      <span className="flex items-center gap-1.5 text-[var(--muted)]">
        <Cable size={13} className={publicConfigured && gateway.tunnel_connected ? "text-green-500" : "text-[var(--muted)]"} />
        Public
        {publicConfigured ? (
          <>
            <span className="text-[var(--foreground)] font-mono">{gateway.public_domain}</span>
            <span className={gateway.tunnel_connected ? "text-green-500 text-xs" : "text-red-500 text-xs"}>
              {gateway.tunnel_connected ? "● tunnel up" : "○ tunnel down"}
            </span>
          </>
        ) : (
          <span className="text-[var(--muted)]">not configured</span>
        )}
      </span>
      <button
        onClick={() => setEditing(true)}
        className="ml-auto flex items-center gap-1 text-xs px-2 py-0.5 rounded text-[var(--muted)] hover:text-[var(--foreground)]"
      >
        <Pencil size={11} /> Edit
      </button>
      {saved && <span className="text-xs text-green-500">{saved.message}</span>}
    </div>
  )
}

const INPUT =
  "bg-black/30 border border-[var(--border)] rounded px-2 py-1 text-sm font-mono w-64 focus:outline-none focus:border-[var(--primary)]"

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-3">
      <span className="w-28 text-[var(--muted)]">{label}</span>
      {children}
    </label>
  )
}
