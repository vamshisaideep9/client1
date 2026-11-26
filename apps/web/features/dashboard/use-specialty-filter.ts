"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth/session-provider";

import { productParam } from "./product-specialty";
import { useMe } from "./me-provider";
import { roleProfileFor } from "./role-badge";

/** The signed-in Telecaller's or Officer's own product specialty id, if any. */
export function useOwnSpecialtyId(): string | null {
  const { session } = useAuth();
  const { me } = useMe();
  if (!session || (session.role !== "telecaller" && session.role !== "employee")) return null;
  return roleProfileFor(me?.roleProfiles, session.role, session.businessLine)?.loan_specialty_id ?? null;
}

/**
 * Presets a list's product filter once: a home link's `?product=` first,
 * otherwise the caller's specialty. It runs once per visit, so clearing the
 * "My product" chip keeps the full list. `enabled` is false off the loans line.
 */
export function useDefaultProductFilter(enabled: boolean, apply: (productId: string) => void): string | null {
  const searchParams = useSearchParams();
  const specialtyId = useOwnSpecialtyId();
  const linked = productParam(searchParams);
  const applied = React.useRef(false);
  const target = linked ?? specialtyId;
  React.useEffect(() => {
    if (applied.current || !enabled || !target) return;
    applied.current = true;
    apply(target);
  }, [enabled, target, apply]);
  return specialtyId;
}
