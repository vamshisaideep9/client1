"use client";

import * as React from "react";

import { captureIncomingReferral } from "@/lib/referral-share";

// Keeps a ?ref=CODE from a shared loan or property link for the browser
// session, so a visitor who browses before signing up is still attributed.
// Renders nothing; the server remains the only place a referral is recorded.
export function ReferralCapture() {
  React.useEffect(() => {
    captureIncomingReferral(window.location.search);
  }, []);
  return null;
}
