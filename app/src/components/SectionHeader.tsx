import { SECTION_HEADERS } from "@/lib/labels"

export function SectionHeader({ section }: { section: string }) {
  const info = SECTION_HEADERS[section]
  return (
    <div className="mb-3">
      <h2 className="text-lg font-semibold">{info?.title ?? section}</h2>
      <p className="text-sm text-[var(--muted)]">{info?.subtitle}</p>
    </div>
  )
}
