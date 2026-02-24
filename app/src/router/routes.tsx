import { createBrowserRouter } from "react-router-dom"
import { Dashboard } from "@/pages/Dashboard"
import { ServiceDetailPage } from "@/pages/ServiceDetail"
import { ScheduledDetailPage } from "@/pages/ScheduledDetail"
import { ComponentDetailPage } from "@/pages/ComponentDetail"
import { ComponentRedirect } from "@/pages/ComponentRedirect"
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
    path: "/components/:name",
    element: <ComponentDetailPage />,
  },
  {
    path: "/component/:name",
    element: <ComponentRedirect />,
  },
  {
    path: "/node/:hostname",
    element: <NodeDetailPage />,
  },
])
