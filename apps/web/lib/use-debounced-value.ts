"use client";

import * as React from "react";

/**
 * `value`, settled: it changes only after `delayMs` without a new value, so a
 * typed amount filter fetches once, not on every keystroke. Values are
 * compared with `JSON.stringify` so an equal object does not restart the wait.
 */
export function useDebouncedValue<T>(value: T, delayMs = 400): T {
  const [settled, setSettled] = React.useState(value);
  const key = JSON.stringify(value);
  React.useEffect(() => {
    const timer = window.setTimeout(
      () => setSettled((previous) => (JSON.stringify(previous) === key ? previous : value)),
      delayMs,
    );
    return () => window.clearTimeout(timer);
    // `key` stands in for `value`: an equal value keeps the pending timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, delayMs]);
  return settled;
}
