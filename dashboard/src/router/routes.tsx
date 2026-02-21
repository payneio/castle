import { createBrowserRouter } from "react-router-dom"
import { Dashboard } from "@/pages/Dashboard"
import { ComponentDetailPage } from "@/pages/ComponentDetail"

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Dashboard />,
  },
  {
    path: "/:name",
    element: <ComponentDetailPage />,
  },
])
