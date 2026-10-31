import { useCallback, useEffect, useState } from "react";

export const ROUTES = [
  "chat",
  "research",
  "travel",
  "email",
  "calendar",
  "finance",
  "coding",
  "activity",
  "accounts",
  "settings",
] as const;

export type Route = (typeof ROUTES)[number];

function parse(hash: string): Route {
  const value = hash.replace(/^#\/?/, "").split("?")[0] ?? "";
  return (ROUTES as readonly string[]).includes(value) ? (value as Route) : "chat";
}

export function useRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: Route) => {
    window.location.hash = `#/${next}`;
  }, []);

  return [route, navigate];
}
