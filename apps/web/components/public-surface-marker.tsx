"use client";

import * as React from "react";

// Marks <body> while a public page is mounted so the public glass finish
// (globals.css) also reaches surfaces Radix portals outside the public layout:
// popovers, selects, dialogs and the mobile navigation sheet. Removed on
// unmount, so dashboard and auth pages keep their solid surfaces.
export function PublicSurfaceMarker() {
  React.useEffect(() => {
    document.body.dataset.surface = "public-glass";
    return () => {
      delete document.body.dataset.surface;
    };
  }, []);
  return null;
}
