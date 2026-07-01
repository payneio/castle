import { useEffect } from "react"
import { AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"

interface ConfirmModalProps {
  open: boolean
  title: string
  /** Optional body; multi-line strings render with their line breaks preserved. */
  body?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** A small in-app confirmation dialog. Replaces window.confirm so destructive
 * actions get a styled, readable prompt (bulleted bodies, a danger variant). */
export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel()
      if (e.key === "Enter") onConfirm()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onCancel, onConfirm])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          {danger && <AlertTriangle size={18} className="text-red-400 mt-0.5 shrink-0" />}
          <h3 className="font-semibold">{title}</h3>
        </div>
        {body && (
          <div className="px-5 py-4 text-sm text-[var(--muted)] whitespace-pre-wrap">
            {body}
          </div>
        )}
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[var(--border)]">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm rounded border border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)] hover:border-[var(--primary)] transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className={cn(
              "px-3 py-1.5 text-sm rounded text-white transition-colors",
              danger ? "bg-red-700 hover:bg-red-600" : "bg-blue-700 hover:bg-blue-600",
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
