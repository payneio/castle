import { useMemo } from "react"
import type { JobSummary, HealthStatus } from "@/types"
import { JobCard } from "./JobCard"

interface ScheduledSectionProps {
  jobs: JobSummary[]
  statuses: HealthStatus[]
}

export function ScheduledSection({ jobs, statuses }: ScheduledSectionProps) {
  const statusMap = useMemo(() => new Map(statuses.map((s) => [s.id, s])), [statuses])

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} health={statusMap.get(job.id)} />
      ))}
    </div>
  )
}
