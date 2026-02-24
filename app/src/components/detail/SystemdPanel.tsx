import { useState } from "react"
import { useSystemdUnit } from "@/services/api/hooks"
import type { SystemdInfo } from "@/types"

interface SystemdPanelProps {
  name: string
  systemd: SystemdInfo
}

export function SystemdPanel({ name, systemd }: SystemdPanelProps) {
  const [showUnit, setShowUnit] = useState(false)
  const { data: unitData } = useSystemdUnit(name, showUnit)

  return (
    <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-5 mb-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-[var(--muted)] uppercase tracking-wider">
          Systemd
        </h2>
        <button
          onClick={() => setShowUnit((v) => !v)}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          {showUnit ? "Hide unit file" : "View unit file"}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm mt-3">
        <span className="text-[var(--muted)]">Unit</span>
        <span className="font-mono">{systemd.unit_name}</span>
        <span className="text-[var(--muted)]">Path</span>
        <span className="font-mono">{systemd.unit_path}</span>
        {systemd.timer && (
          <>
            <span className="text-[var(--muted)]">Timer</span>
            <span>Active</span>
          </>
        )}
      </div>
      {showUnit && unitData && (
        <div className="mt-4 space-y-3">
          <div>
            <span className="text-xs text-[var(--muted)] block mb-1">{systemd.unit_name}</span>
            <pre className="text-sm whitespace-pre-wrap bg-[var(--background)] rounded p-3 border border-[var(--border)] font-mono overflow-x-auto">
              {unitData.service}
            </pre>
          </div>
          {unitData.timer && (
            <div>
              <span className="text-xs text-[var(--muted)] block mb-1">
                {systemd.unit_name.replace(".service", ".timer")}
              </span>
              <pre className="text-sm whitespace-pre-wrap bg-[var(--background)] rounded p-3 border border-[var(--border)] font-mono overflow-x-auto">
                {unitData.timer}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
