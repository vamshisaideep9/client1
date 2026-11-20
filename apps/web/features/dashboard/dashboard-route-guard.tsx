"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";

import { setEmailRequiredHint, useAuth } from "@/components/auth/session-provider";

import { useLine } from "./line-provider";
import { useMe } from "./me-provider";
import { isDashboardPathAllowed } from "./nav-items";
import { DashboardPageSkeleton } from "./dashboard-page-skeleton";

// Consistent dashboard UX gate for direct URL entry. This reads the same
// role/line capability catalogue as the sidebar, but it is never an
// authorization boundary: API dependencies, service checks, and RLS still
// decide whether data can be read or changed.
//
// CS-025: an account that still owes a verified email (the server's
// `email_required`, from /auth/me or the session tokens) is sent to the
// blocking /add-email step; the API refuses its business endpoints anyway.
export function DashboardRouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session } = useAuth();
  const { me } = useMe();
  const { activeLine, lines } = useLine();

  const emailRequired = me ? me.emailRequired : (session?.emailRequired ?? false);

  const allowed =
    session != null &&
    !emailRequired &&
    isDashboardPathAllowed(pathname, {
      role: session.role,
      businessLine: session.businessLine,
      activeLine,
      // An unavailable /auth/me response must not become a browser auth wall.
      // Once known, held Client lines make cross-line direct URLs deterministic.
      profileLines: lines.length > 0 ? lines : undefined,
      staffFeatures: session.staffFeatures,
    });

  React.useEffect(() => {
    if (session == null) return;
    // Keep the edge hint in step with the server's answer.
    if (me) setEmailRequiredHint(me.emailRequired);
    if (emailRequired) router.replace("/add-email");
    else if (!allowed) router.replace("/dashboard");
  }, [allowed, emailRequired, me, router, session]);

  if (!allowed) {
    return <DashboardPageSkeleton label="Checking dashboard access" />;
  }

  return <>{children}</>;
}
