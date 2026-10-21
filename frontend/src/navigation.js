import { useCallback, useEffect, useState } from "react";

export function useBrowserNavigation() {
  const [pathname, setPathname] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((path, { replace = false } = {}) => {
    if (window.location.pathname !== path) {
      window.history[replace ? "replaceState" : "pushState"]({}, "", path);
      setPathname(path);
    }
    window.scrollTo({ top: 0, behavior: "auto" });
  }, []);

  return { pathname, navigate };
}
