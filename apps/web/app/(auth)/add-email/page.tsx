"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut, Mail } from "lucide-react";

import { AddEmailForm } from "@/components/auth/add-email-form";
import { AuthPageSkeleton } from "@/components/auth/auth-page-skeleton";
import { AuthShell } from "@/components/auth/auth-shell";
import { useAuth } from "@/components/auth/session-provider";
import { Button } from "@/components/ui/button";
import { StaffContactRequestDialog } from "@/features/settings/staff-contact-request-dialog";
import { ADMIN_MANAGED_ROLES } from "@/features/settings/settings-by-role";
import { getMe, logout, type Me } from "@/lib/auth";
import { getActiveContactChange } from "@/lib/contact-change";

// CS-025 blocking step. When the server enforces mandatory email, an account
// without a verified one lands here after sign-in (middleware.ts and the
// dashboard route guard route it) and every API endpoint except this step,
// /auth/me, logout and account deletion answers 403 until it is done.
export default function AddEmailPage() {
  const router = useRouter();
  const { session, isLoading, isAuthenticated, setEmailRequired, clear } = useAuth();
  const [me, setMe] = React.useState<Me | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [requestOpen, setRequestOpen] = React.useState(false);
  const [requestPending, setRequestPending] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoadError(null);
    const res = await getMe();
    if (!res.ok) {
      setLoadError(res.error);
      return;
    }
    setMe(res.data);
    if (!res.data.emailRequired) {
      setEmailRequired(false);
      router.replace("/dashboard");
    }
  }, [router, setEmailRequired]);

  React.useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace("/login?return_to=%2Fdashboard");
      return;
    }
    void load();
  }, [isAuthenticated, isLoading, load, router]);

  const staff = session ? ADMIN_MANAGED_ROLES.has(session.role) : false;

  React.useEffect(() => {
    if (!staff || !isAuthenticated) return;
    void getActiveContactChange().then((res) => {
      if (res.ok) setRequestPending(res.data?.status === "pending_approval");
    });
  }, [staff, isAuthenticated, requestOpen]);

  async function signOut() {
    await logout();
    clear();
    router.replace("/login");
  }

  if (isLoading || !isAuthenticated || (!me && !loadError)) {
    return <AuthPageSkeleton />;
  }

  return (
    <AuthShell
      scene="login"
      panelTitle="One more step to secure your account."
      panelSubtitle="A verified email lets us reach you about sign-ins and changes to your account, and helps you recover it."
    >
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl text-brand-link">
        <Mail className="h-6 w-6" aria-hidden="true" />
      </span>
      <div className="mb-5 space-y-2">
        <h1 className="font-heading text-3xl font-bold text-text-primary">Add your email</h1>
        <p className="text-base text-text-secondary">
          Every account now needs a verified email. Add yours to continue to your dashboard.
        </p>
      </div>

      {loadError ? (
        <div className="space-y-3" role="alert">
          <p className="text-sm text-destructive">{loadError}</p>
          <Button variant="outline" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : me ? (
        <>
          {requestPending ? (
            <p className="mb-4 rounded-lg border border-border bg-muted/40 p-3 text-sm text-text-secondary">
              Your request to change your email is waiting for an Admin. You can continue once it
              is approved, or verify the email on file below.
            </p>
          ) : null}
          <AddEmailForm
            emailOnFile={me.email}
            staff={staff}
            onVerified={async () => {
              setEmailRequired(false);
              router.replace("/dashboard");
            }}
            onRequestChange={() => setRequestOpen(true)}
          />
          {staff ? (
            <StaffContactRequestDialog
              open={requestOpen}
              onOpenChange={setRequestOpen}
              initialField="email"
              onSubmitted={() => setRequestPending(true)}
            />
          ) : null}
        </>
      ) : null}

      <div className="mt-8 border-t border-border pt-5">
        <Button variant="ghost" onClick={() => void signOut()} className="text-text-secondary">
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Sign out
        </Button>
      </div>
    </AuthShell>
  );
}
