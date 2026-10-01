import { useCallback, useEffect, useState } from "react";

// Stable, shareable URLs: every non-sensitive setting lives in the query string.
export function useUrlState(): [URLSearchParams, (patch: Record<string, string | null>, replace?: boolean) => void] {
  const [params, setParams] = useState(() => new URLSearchParams(window.location.search));
  useEffect(() => {
    const on = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  const update = useCallback((patch: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k); else next.set(k, v);
    }
    const url = `${window.location.pathname}?${next.toString()}`;
    if (replace) window.history.replaceState(null, "", url); else window.history.pushState(null, "", url);
    setParams(next);
    if (!replace) window.scrollTo({ top: 0 });
  }, []);
  return [params, update];
}

export function hrefFor(patch: Record<string, string>): string {
  return `?${new URLSearchParams(patch).toString()}`;
}
