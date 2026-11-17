"use client";

import * as React from "react";

import { listBanners, type Banner } from "@/lib/banners-api";

import { startQueueRefresh } from "./queue-refresh";

// Fetches every banner (shared queue: sub_admin and admin both see all
// statuses, not just pending). Exposes the async triad + a refetch used after
// create/submit/approve/reject so the list stays in sync.
//
// The queue also refreshes itself (every 30 s while the tab is visible, and on
// return to the tab) so an approval that publishes a banner, or a teammate's
// change, shows up without a reload. Background reads are silent: no loading
// skeleton, and a failed background read keeps the rows already on screen.
// Open workspaces keep their own copy of the selected banner, so a refresh
// never touches unsaved edits (see refreshedSelection in queue-refresh.ts).
export function useBannerQueue() {
  const [items, setItems] = React.useState<Banner[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const latestRequest = React.useRef(0);
  const hasRows = React.useRef(false);

  const load = React.useCallback(async (silent = false) => {
    const request = ++latestRequest.current;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    const res = await listBanners();
    // A newer read (an action's reload or a later poll) owns the state now.
    if (request !== latestRequest.current) return;
    if (res.ok) {
      hasRows.current = true;
      setItems(res.data);
      setError(null);
    } else if (!silent || !hasRows.current) {
      setError(res.error);
    }
    setLoading(false);
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => startQueueRefresh(() => void load(true)), [load]);

  const reload = React.useCallback(() => load(), [load]);
  return { items, loading, error, reload };
}
