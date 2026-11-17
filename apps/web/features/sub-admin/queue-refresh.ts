// Background refresh for the shared campaign queues. Sub Admins and Admins
// work the same banner queue from different screens, and approval can now
// publish a banner at once, so each open queue re-reads itself every 30 s
// while its tab is visible and immediately when the tab regains focus.
//
// Kept framework-free so the timing rules are unit-testable without a DOM.

export const QUEUE_POLL_MS = 30_000;
// Returning to a tab fires both `visibilitychange` and `focus`; one read is
// enough.
const MIN_GAP_MS = 2_000;

type EventSource = {
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
};

export type QueueRefreshEnvironment = {
  doc: EventSource & { visibilityState: DocumentVisibilityState };
  win: EventSource;
  setInterval: (handler: () => void, ms: number) => unknown;
  clearInterval: (id: unknown) => void;
  now: () => number;
};

function browserEnvironment(): QueueRefreshEnvironment {
  return {
    doc: document,
    win: window,
    setInterval: (handler, ms) => window.setInterval(handler, ms),
    clearInterval: (id) => window.clearInterval(id as number),
    now: () => Date.now(),
  };
}

/** Starts polling plus focus/visibility refetch; returns the cleanup. */
export function startQueueRefresh(
  refresh: () => void,
  intervalMs: number = QUEUE_POLL_MS,
  env: QueueRefreshEnvironment = browserEnvironment(),
): () => void {
  let last = env.now();
  const refreshIfVisible = () => {
    if (env.doc.visibilityState !== "visible") return;
    const now = env.now();
    if (now - last < MIN_GAP_MS) return;
    last = now;
    refresh();
  };
  const timer = env.setInterval(refreshIfVisible, intervalMs);
  env.doc.addEventListener("visibilitychange", refreshIfVisible);
  env.win.addEventListener("focus", refreshIfVisible);
  return () => {
    env.clearInterval(timer);
    env.doc.removeEventListener("visibilitychange", refreshIfVisible);
    env.win.removeEventListener("focus", refreshIfVisible);
  };
}

type Selectable = { id: string; version: number; status: string; updated_at: string };

/**
 * The open workspace's banner after a background refresh. Local work wins:
 * while the author has unsaved edits, an action is running, or a reviewer is
 * writing a note, the selection is left exactly as it is. Otherwise a newer
 * server copy replaces it; the same object is returned when nothing changed.
 */
export function refreshedSelection<T extends Selectable>(
  active: T | null,
  items: readonly T[],
  keepLocal: boolean,
): T | null {
  if (!active || keepLocal) return active;
  const fresh = items.find((item) => item.id === active.id);
  if (!fresh) return active;
  const changed =
    fresh.version !== active.version ||
    fresh.status !== active.status ||
    fresh.updated_at !== active.updated_at;
  return changed ? fresh : active;
}
