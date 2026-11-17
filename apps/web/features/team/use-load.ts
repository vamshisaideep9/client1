"use client";

import * as React from "react";

import type { ApiResponse } from "@/lib/api/client";

export type Load<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: string; code: number | null };

/**
 * Fetch on mount and whenever `deps` change. A refetch keeps the last good
 * data on screen (no flash back to skeletons when the period changes), and a
 * response for stale deps is dropped.
 */
export function useLoad<T>(load: () => Promise<ApiResponse<T>>, deps: React.DependencyList) {
  const [state, setState] = React.useState<Load<T>>({ status: "loading" });
  const [reloadKey, setReloadKey] = React.useState(0);
  const loadRef = React.useRef(load);
  loadRef.current = load;

  React.useEffect(() => {
    let active = true;
    setState((current) => (current.status === "ready" ? current : { status: "loading" }));
    void loadRef.current().then((res) => {
      if (!active) return;
      setState(
        res.ok
          ? { status: "ready", data: res.data }
          : { status: "error", error: res.error, code: res.status },
      );
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass the inputs of `load`.
  }, [...deps, reloadKey]);

  const retry = React.useCallback(() => setReloadKey((key) => key + 1), []);
  return { state, retry };
}
