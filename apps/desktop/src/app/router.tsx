import { createHashRouter, Navigate, RouterProvider } from "react-router";
import { APP_ROUTES, resolveInitialRoute } from "../contracts/routes.ts";
import { ControlCenterPage } from "../pages/ControlCenterPage.tsx";
import { PopupPage } from "../pages/PopupPage.tsx";
import { RegionSelectorPage } from "../pages/RegionSelectorPage.tsx";

export const appRoutes = [
  { path: APP_ROUTES.controlCenter, element: <ControlCenterPage /> },
  { path: APP_ROUTES.popup, element: <PopupPage /> },
  { path: APP_ROUTES.regionSelector, element: <RegionSelectorPage /> },
  { path: "*", element: <Navigate to={APP_ROUTES.controlCenter} replace /> },
];

if (!window.location.hash) {
  window.location.hash = resolveInitialRoute(window.location.search);
}

export const appRouter = createHashRouter(appRoutes);

export function AppRouter() {
  return <RouterProvider router={appRouter} />;
}
