import { createBrowserRouter, Navigate } from "react-router-dom"
import { Layout } from "@/components/Layout"
import { Overview } from "@/pages/Overview"
import { Services } from "@/pages/Services"
import { Scheduled } from "@/pages/Scheduled"
import { Tools } from "@/pages/Tools"
import { Stacks } from "@/pages/Stacks"
import { Programs } from "@/pages/Programs"
import { GatewayPage } from "@/pages/GatewayPage"
import { MeshPage } from "@/pages/MeshPage"
import { SecretsPage } from "@/pages/SecretsPage"
import { SystemMapPage } from "@/pages/SystemMap"
import { ServiceDetailPage } from "@/pages/ServiceDetail"
import { ScheduledDetailPage } from "@/pages/ScheduledDetail"
import { ToolDetailPage } from "@/pages/ToolDetail"
import { ProgramDetailPage } from "@/pages/ProgramDetail"
import { ProgramRedirect } from "@/pages/ProgramRedirect"
import { NodeDetailPage } from "@/pages/NodeDetail"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Overview /> },
      { path: "services", element: <Services /> },
      { path: "scheduled", element: <Scheduled /> },
      { path: "tools", element: <Tools /> },
      { path: "stacks", element: <Stacks /> },
      { path: "programs", element: <Programs /> },
      { path: "gateway", element: <GatewayPage /> },
      { path: "mesh", element: <MeshPage /> },
      { path: "secrets", element: <SecretsPage /> },
      { path: "system", element: <SystemMapPage /> },
      // Back-compat: the page was formerly at /map. Redirect old links/bookmarks.
      { path: "map", element: <Navigate to="/system" replace /> },
      { path: "services/:name", element: <ServiceDetailPage /> },
      { path: "jobs/:name", element: <ScheduledDetailPage /> },
      { path: "tools/:name", element: <ToolDetailPage /> },
      { path: "programs/:name", element: <ProgramDetailPage /> },
      { path: "deployment/:name", element: <ProgramRedirect /> },
      { path: "node/:hostname", element: <NodeDetailPage /> },
    ],
  },
])
