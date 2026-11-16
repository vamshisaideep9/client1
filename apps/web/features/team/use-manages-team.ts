"use client";

import * as React from "react";

import { getMyTeams } from "@/lib/staff-teams-api";

// Navigation hint only: whether this Sub Admin manages a live team. The answer
// is cached per account for the page session so the sidebar asks once; the
// manager API and RLS remain the access boundary.
const cache = new Map<string, Promise<boolean>>();

function load(accountKey: string): Promise<boolean> {
  let pending = cache.get(accountKey);
  if (!pending) {
    pending = getMyTeams().then((res) => res.ok && res.data.teams.length > 0);
    cache.set(accountKey, pending);
    // A failed check must be retried on the next mount, not remembered.
    void pending.then((manages) => {
      if (!manages) cache.delete(accountKey);
    });
  }
  return pending;
}

export function useManagesTeam(role: string | undefined, accountKey: string | undefined) {
  const [manages, setManages] = React.useState(false);
  React.useEffect(() => {
    if (role !== "sub_admin" || !accountKey) {
      setManages(false);
      return;
    }
    let active = true;
    void load(accountKey).then((value) => {
      if (active) setManages(value);
    });
    return () => {
      active = false;
    };
  }, [role, accountKey]);
  return manages;
}
