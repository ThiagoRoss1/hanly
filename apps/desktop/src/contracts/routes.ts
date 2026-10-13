export const APP_ROUTES = {
  controlCenter: "/",
  popup: "/popup",
  regionSelector: "/region-selector",
} as const;

export type DesktopView = keyof typeof APP_ROUTES;

export function resolveInitialRoute(search: string): string {
  const requestedView = new URLSearchParams(search).get("view");
  if (requestedView === "popup") return APP_ROUTES.popup;
  if (requestedView === "region_selector") return APP_ROUTES.regionSelector;
  return APP_ROUTES.controlCenter;
}
