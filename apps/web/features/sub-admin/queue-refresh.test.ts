import { describe, expect, it, vi } from "vitest";

import {
  QUEUE_POLL_MS,
  refreshedSelection,
  startQueueRefresh,
  type QueueRefreshEnvironment,
} from "./queue-refresh";

function fakeEnvironment() {
  let clock = 0;
  let tick: (() => void) | null = null;
  const doc = Object.assign(new EventTarget(), {
    visibilityState: "visible" as DocumentVisibilityState,
  });
  const win = new EventTarget();
  const cleared: unknown[] = [];
  const env: QueueRefreshEnvironment = {
    doc,
    win,
    setInterval: (handler, ms) => {
      expect(ms).toBe(QUEUE_POLL_MS);
      tick = handler;
      return "timer";
    },
    clearInterval: (id) => cleared.push(id),
    now: () => clock,
  };
  return {
    env,
    doc,
    win,
    cleared,
    advance(ms: number) {
      clock += ms;
    },
    fireInterval() {
      tick?.();
    },
  };
}

describe("startQueueRefresh", () => {
  it("polls every 30 s while the tab is visible", () => {
    const fake = fakeEnvironment();
    const refresh = vi.fn();
    startQueueRefresh(refresh, QUEUE_POLL_MS, fake.env);

    fake.advance(QUEUE_POLL_MS);
    fake.fireInterval();
    expect(refresh).toHaveBeenCalledTimes(1);

    fake.doc.visibilityState = "hidden";
    fake.advance(QUEUE_POLL_MS);
    fake.fireInterval();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("refetches when the tab becomes visible or regains focus, once per return", () => {
    const fake = fakeEnvironment();
    const refresh = vi.fn();
    startQueueRefresh(refresh, QUEUE_POLL_MS, fake.env);

    fake.doc.visibilityState = "hidden";
    fake.advance(10_000);
    fake.doc.dispatchEvent(new Event("visibilitychange"));
    expect(refresh).not.toHaveBeenCalled();

    fake.doc.visibilityState = "visible";
    fake.doc.dispatchEvent(new Event("visibilitychange"));
    fake.win.dispatchEvent(new Event("focus"));
    expect(refresh).toHaveBeenCalledTimes(1);

    fake.advance(5_000);
    fake.win.dispatchEvent(new Event("focus"));
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("stops listening on cleanup", () => {
    const fake = fakeEnvironment();
    const refresh = vi.fn();
    const stop = startQueueRefresh(refresh, QUEUE_POLL_MS, fake.env);
    stop();
    fake.advance(60_000);
    fake.win.dispatchEvent(new Event("focus"));
    fake.doc.dispatchEvent(new Event("visibilitychange"));
    expect(refresh).not.toHaveBeenCalled();
    expect(fake.cleared).toEqual(["timer"]);
  });
});

describe("refreshedSelection", () => {
  const base = { id: "b1", version: 2, status: "pending_approval", updated_at: "2026-11-16T10:00:00Z" };

  it("adopts the newer server copy when there is no local work", () => {
    const live = { ...base, version: 3, status: "live", updated_at: "2026-11-16T10:01:00Z" };
    expect(refreshedSelection(base, [live], false)).toBe(live);
  });

  it("never replaces a selection with unsaved local work", () => {
    const live = { ...base, version: 3, status: "live" };
    expect(refreshedSelection(base, [live], true)).toBe(base);
  });

  it("keeps the same object when nothing changed or the row is gone", () => {
    expect(refreshedSelection(base, [{ ...base }], false)).toBe(base);
    expect(refreshedSelection(base, [], false)).toBe(base);
    expect(refreshedSelection(null, [base], false)).toBeNull();
  });
});
