import { createBrowserRouter } from "react-router-dom"
import { Dashboard } from "@/pages/Dashboard"
import { ServiceDetailPage } from "@/pages/ServiceDetail"
import { ScheduledDetailPage } from "@/pages/ScheduledDetail"
import { ProgramDetailPage } from "@/pages/ProgramDetail"
import { ProgramRedirect } from "@/pages/ProgramRedirect"
import { NodeDetailPage } from "@/pages/NodeDetail"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Dashboard />,
  },
  {
    path: "/services/:name",
    element: <ServiceDetailPage />,
  },
  {
    path: "/jobs/:name",
    element: <ScheduledDetailPage />,
  },
  {
    path: "/programs/:name",
    element: <ProgramDetailPage />,
  },
  {
    path: "/component/:name",
    element: <ProgramRedirect />,
  },
  {
    path: "/node/:hostname",
    element: <NodeDetailPage />,
  },
])
