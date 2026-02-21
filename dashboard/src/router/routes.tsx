import { createBrowserRouter } from "react-router-dom"
import { Dashboard } from "@/pages/Dashboard"
import { ComponentDetailPage } from "@/pages/ComponentDetail"
import { ConfigEditorPage } from "@/pages/ConfigEditor"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Dashboard />,
  },
  {
    path: "/config",
    element: <ConfigEditorPage />,
  },
  {
    path: "/:name",
    element: <ComponentDetailPage />,
  },
])
