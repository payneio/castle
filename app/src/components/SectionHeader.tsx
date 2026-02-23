import { SECTION_HEADERS } from "@/lib/labels"

export function SectionHeader({ category }: { category: string }) {
  const info = SECTION_HEADERS[category]
  return (
    <div className="mb-3">
      <h2 className="text-lg font-semibold">{info?.title ?? category}</h2>
      <p className="text-sm text-[var(--muted)]">{info?.subtitle}</p>
    </div>
  )
}
