import { useCallback, useState } from "react"
import {
  Bot,
  ChevronDown,
  History,
  Maximize2,
  Minimize2,
  Play,
  RotateCw,
  Terminal as TerminalIcon,
  Trash2,
} from "lucide-react"
import { AgentTerminal } from "@/components/AgentTerminal"
import {
  useAgents,
  useAgentHistory,
  useAgentSessions,
  useDeleteAgentSession,
} from "@/services/api/hooks"
import { cn } from "@/lib/utils"

// The reserved name that launches the plain login shell (backend TERMINAL_AGENT).
const SHELL = "terminal"

interface Active {
  agent: string
  resumeId?: string
  mode?: "continue"
  resumeSessionId?: string
  key: number // bump to force a fresh terminal mount (relaunch / resume)
}

// A global, persistent assistant surface: a floating action button that opens an
// overlay panel. It lives in Layout (which does not remount on navigation) and
// keeps the terminal mounted while minimized, so the agent session and its
// WebSocket survive as you click around the rest of the dashboard.
export function AssistantDock() {
  const { data: agents } = useAgents()
  const { data: sessions } = useAgentSessions()
  const deleteSession = useDeleteAgentSession()

  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [active, setActive] = useState<Active | null>(null)
  const [seq, setSeq] = useState(0)

  const { data: history } = useAgentHistory(showSessions)

  const launch = (
    agent: string,
    opts?: { resumeId?: string; mode?: "continue"; resumeSessionId?: string },
  ) => {
    const key = seq + 1
    setSeq(key)
    setActive({
      agent,
      resumeId: opts?.resumeId,
      mode: opts?.mode,
      resumeSessionId: opts?.resumeSessionId,
      key,
    })
    setOpen(true)
    setShowSessions(false)
  }
  const relaunch = () => active && launch(active.agent)

  const onSession = useCallback(() => {
    /* session id confirmed; list auto-refreshes via its 5s poll */
  }, [])

  const runningCount = sessions?.filter((s) => s.running).length ?? 0

  const pill =
    "text-xs px-2.5 py-1 rounded-full border transition-colors inline-flex items-center gap-1.5"
  const pillIdle =
    "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)]"
  const iconBtn =
    "p-1 rounded text-[var(--muted)] hover:text-[var(--foreground)] hover:bg-white/10 transition-colors"

  return (
    <>
      {/* FAB — hidden while the panel is open */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-40 w-14 h-14 rounded-full bg-[var(--primary)] text-black shadow-lg flex items-center justify-center hover:opacity-90 transition-opacity"
          title="Assistant"
          aria-label="Open assistant"
        >
          <Bot size={24} />
          {runningCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full bg-green-400 border-2 border-[var(--background)]" />
          )}
        </button>
      )}

      {/* Overlay panel — kept mounted (translated off-screen when closed) so the
          terminal's WebSocket survives minimize. */}
      <div
        className={cn(
          "fixed z-40 flex flex-col",
          expanded
            ? "inset-4"
            : "bottom-4 right-4 w-[760px] max-w-[calc(100vw-2rem)] h-[600px] max-h-[calc(100vh-2rem)]",
          "bg-[var(--background)] border border-[var(--border)] rounded-xl shadow-2xl",
          "transition-all duration-200",
          open
            ? "opacity-100 translate-y-0"
            : "opacity-0 translate-y-[calc(100%+2rem)] pointer-events-none",
        )}
        aria-hidden={!open}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border)]">
          <Bot size={16} className="text-[var(--primary)] shrink-0" />
          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
            <button
              onClick={() => launch(SHELL)}
              className={cn(
                pill,
                active?.agent === SHELL && !active.resumeId
                  ? "border-[var(--primary)] text-[var(--foreground)]"
                  : pillIdle,
              )}
              title="Plain login shell in the castle repo"
            >
              <TerminalIcon size={13} /> Shell
            </button>
            {agents?.map((a) => (
              <button
                key={a.name}
                onClick={() => a.available && launch(a.name)}
                disabled={!a.available}
                className={cn(
                  pill,
                  !a.available && "opacity-40 cursor-not-allowed",
                  active?.agent === a.name && !active.resumeId
                    ? "border-[var(--primary)] text-[var(--foreground)]"
                    : pillIdle,
                )}
                title={a.available ? a.description ?? a.name : `${a.command} not installed`}
              >
                <Bot size={13} /> {a.name}
              </button>
            ))}
            {/* resume: chip = open the agent's own in-terminal picker. Agents
                that expose a machine-readable session list appear in the History
                popover instead (no chip needed). */}
            {agents?.some((a) => a.available && a.can_continue && !a.can_list_sessions) && (
              <span className="text-[10px] text-[var(--muted)] pl-1">resume:</span>
            )}
            {agents
              ?.filter((a) => a.available && a.can_continue && !a.can_list_sessions)
              .map((a) => (
                <button
                  key={`cont-${a.name}`}
                  onClick={() => launch(a.name, { mode: "continue" })}
                  className={cn(pill, pillIdle)}
                  title={`Open ${a.name}'s session picker in this directory`}
                >
                  <RotateCw size={12} /> {a.name}
                </button>
              ))}
          </div>
          <div className="ml-auto flex items-center gap-0.5 shrink-0">
            {active && (
              <button onClick={relaunch} className={iconBtn} title="Restart session">
                <RotateCw size={14} />
              </button>
            )}
            <button
              onClick={() => setShowSessions((s) => !s)}
              className={cn(iconBtn, showSessions && "text-[var(--foreground)] bg-white/10")}
              title="Sessions"
            >
              <History size={15} />
            </button>
            <button
              onClick={() => setExpanded((e) => !e)}
              className={iconBtn}
              title={expanded ? "Shrink" : "Expand"}
            >
              {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button onClick={() => setOpen(false)} className={iconBtn} title="Minimize">
              <ChevronDown size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="relative flex-1 min-h-0 p-2">
          {active ? (
            <AgentTerminal
              key={active.key}
              agent={active.agent}
              resumeId={active.resumeId}
              mode={active.mode}
              resumeSessionId={active.resumeSessionId}
              onSession={onSession}
              fill
            />
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-[var(--muted)]">
              Pick an agent above to start a session.
            </div>
          )}

          {/* Sessions popover */}
          {showSessions && (
            <div className="absolute inset-x-2 top-2 max-h-[calc(100%-1rem)] overflow-auto bg-[var(--background)] border border-[var(--border)] rounded-lg shadow-xl">
              <div className="px-3 py-2 text-xs font-semibold border-b border-[var(--border)]">
                Sessions
              </div>
              {sessions && sessions.length > 0 ? (
                <div className="divide-y divide-[var(--border)]">
                  {sessions.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                      <span
                        className={cn(
                          "w-2 h-2 rounded-full shrink-0",
                          s.running ? "bg-green-400" : "bg-[var(--muted)]",
                        )}
                        title={s.running ? "running" : "exited"}
                      />
                      <span className="font-medium">{s.agent}</span>
                      <span className="text-[var(--muted)] font-mono">{s.id}</span>
                      <span className="text-[var(--muted)] ml-auto">
                        {s.running ? `${s.clients} client${s.clients === 1 ? "" : "s"}` : `exit ${s.exit_code ?? "?"}`}
                      </span>
                      <button
                        onClick={() => launch(s.agent, { resumeId: s.id })}
                        disabled={!s.running}
                        className={cn(
                          "p-1 rounded hover:bg-white/10 transition-colors",
                          s.running
                            ? "text-[var(--muted)] hover:text-[var(--foreground)]"
                            : "opacity-30 cursor-not-allowed",
                        )}
                        title="Resume"
                      >
                        <Play size={13} />
                      </button>
                      <button
                        onClick={() => deleteSession.mutate(s.id)}
                        className="p-1 rounded text-[var(--muted)] hover:text-red-400 hover:bg-white/10 transition-colors"
                        title="Kill session"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="px-3 py-4 text-xs text-[var(--muted)]">
                  No live sessions.
                </div>
              )}

              {/* Agent-native history — past conversations each agent stored for
                  this directory (from its declared session-list command). */}
              {history && history.length > 0 && (
                <>
                  <div className="px-3 py-2 text-xs font-semibold border-y border-[var(--border)]">
                    History
                  </div>
                  <div className="divide-y divide-[var(--border)]">
                    {history.map((h) => (
                      <button
                        key={`${h.agent}-${h.id}`}
                        onClick={() =>
                          launch(h.agent, { resumeSessionId: h.id })
                        }
                        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-white/5 transition-colors"
                        title={`Resume in ${h.agent}`}
                      >
                        <RotateCw size={12} className="text-[var(--muted)] shrink-0" />
                        <span className="text-[var(--muted)]">{h.agent}</span>
                        <span className="truncate">{h.title || h.id}</span>
                        <span className="text-[var(--muted)] ml-auto shrink-0">
                          {formatTime(h.time)}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function formatTime(t: number | string | null): string {
  if (t == null) return ""
  if (typeof t === "number") return new Date(t).toLocaleString()
  return t
}
