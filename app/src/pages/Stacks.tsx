import { useState } from "react"
import { Link } from "react-router-dom"
import { Check, Copy, Layers, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { useStacksStatus, type StackStatus, type ToolStatus } from "@/services/api/hooks"
import { PageHeader } from "@/components/PageHeader"

// A stack's overall health pill: green when every tool it needs is present, red
// when one is missing, grey when nothing on this node uses it yet.
function StackBadge({ stack }: { stack: StackStatus }) {
  const [label, cls] = !stack.in_use
    ? (["unused", "bg-gray-700/50 text-gray-400"] as const)
    : stack.ok
      ? (["ready", "bg-green-800/50 text-green-300"] as const)
      : (["missing tools", "bg-red-800/50 text-red-300"] as const)
  return (
    <span className={cn("inline-flex items-center text-xs px-2 py-0.5 rounded-full", cls)}>
      {label}
    </span>
  )
}

// A copy-to-clipboard chip for a tool's install command — the "diagnose + copyable
// hint" contract: we never install for you, but the fix is one click from your shell.
function CopyHint({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        void navigator.clipboard?.writeText(text)
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1200)
      }}
      className="group inline-flex items-center gap-1.5 rounded border border-[var(--border)] bg-black/20 px-2 py-1 font-mono text-xs text-[var(--muted)] hover:border-[var(--primary)] hover:text-[var(--foreground)] transition-colors"
      title="Copy install command"
    >
      {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
      <span className="truncate">{text}</span>
    </button>
  )
}

function ToolRow({ tool }: { tool: ToolStatus }) {
  return (
    <div className="flex flex-col gap-1 py-1.5">
      <div className="flex items-center gap-2 text-sm">
        {tool.present ? (
          <Check size={14} className="shrink-0 text-green-400" />
        ) : (
          <X size={14} className="shrink-0 text-red-400" />
        )}
        <span className="font-mono font-medium">{tool.command}</span>
        <span className="text-xs text-[var(--muted)]">
          {tool.purpose} · {tool.phase}
        </span>
        {tool.version && (
          <span className="ml-auto truncate max-w-[45%] text-xs text-[var(--muted)]" title={tool.version}>
            {tool.version}
          </span>
        )}
      </div>
      {!tool.present && (
        <div className="pl-6">
          <CopyHint text={tool.install_hint} />
        </div>
      )}
    </div>
  )
}

function StackCard({ stack }: { stack: StackStatus }) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-[var(--card)] p-4",
        stack.in_use ? "border-[var(--border)]" : "border-[var(--border)] opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">{stack.name}</h2>
        <StackBadge stack={stack} />
      </div>

      <div className="mt-3 divide-y divide-[var(--border)]">
        {stack.tools.length > 0 ? (
          stack.tools.map((t) => <ToolRow key={t.command} tool={t} />)
        ) : (
          <p className="py-1.5 text-sm text-[var(--muted)]">No host tools required.</p>
        )}
      </div>

      {stack.programs.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-[var(--muted)]">used by</span>
          {stack.programs.map((p) => (
            <Link
              key={p}
              to={`/programs/${p}`}
              className="rounded bg-black/20 px-1.5 py-0.5 font-mono hover:text-[var(--primary)]"
            >
              {p}
            </Link>
          ))}
        </div>
      )}

      {stack.verbs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-[var(--muted)]">
          {stack.verbs.map((v) => (
            <span key={v} className="rounded-full border border-[var(--border)] px-1.5 py-0.5">
              {v}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function Stacks() {
  const { data: stacks, isLoading } = useStacksStatus()
  const missing = (stacks ?? []).filter((s) => s.in_use && !s.ok).length

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        title="Stacks"
        subtitle="The toolchains each stack needs, and whether they're present where your services run"
        actions={
          missing > 0 ? (
            <span className="inline-flex items-center gap-1.5 text-sm text-red-400">
              <X size={14} /> {missing} stack{missing !== 1 ? "s" : ""} missing tools
            </span>
          ) : stacks && stacks.length > 0 ? (
            <span className="inline-flex items-center gap-1.5 text-sm text-green-400">
              <Check size={14} /> all toolchains present
            </span>
          ) : null
        }
      />

      {isLoading ? (
        <p className="text-[var(--muted)]">Loading...</p>
      ) : stacks && stacks.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {stacks.map((s) => (
            <StackCard key={s.name} stack={s} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 py-16 text-[var(--muted)]">
          <Layers size={28} />
          <p>No stacks.</p>
        </div>
      )}
    </div>
  )
}
