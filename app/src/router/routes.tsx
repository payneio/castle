import { createBrowserRouter } from "react-router-dom"
import { Dashboard } from "@/pages/Dashboard"
import { ComponentDetailPage } from "@/pages/ComponentDetail"
import { NodeDetailPage } from "@/pages/NodeDetail"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Dashboard />,
  },
  {
    path: "/component/:name",
    element: <ComponentDetailPage />,
  },
  {
    path: "/node/:hostname",
    element: <NodeDetailPage />,
  },
])
