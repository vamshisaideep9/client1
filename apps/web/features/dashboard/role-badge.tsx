"use client";

import * as React from "react";

import type { components } from "@contracts/generated/schema";
import { Badge } from "@/components/ui/badge";
import type { StaffBusinessLine, UserRole } from "@/lib/auth";
import { useAuth } from "@/components/auth/session-provider";
import { useMe } from "./me-provider";
import { useLine } from "./line-provider";

export type RoleProfile = components["schemas"]["RoleProfileRead"];
const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Admin", sub_admin: "Sub Admin", agent: "Agent", telecaller: "Telecaller",
  employee: "Employee", client: "Client",
};
const LINE_LABEL: Record<StaffBusinessLine, string> = {
  loans: "Loans", real_estate: "Real Estate", both: "Loans and Real Estate",
};

export function roleProfileFor(profiles: RoleProfile[] | undefined, role: UserRole, line: StaffBusinessLine | null) {
  const platformRole = role === "admin" || role === "sub_admin";
  return profiles?.find((profile) => profile.role === role &&
    (platformRole || line === null || profile.business_line === line || profile.business_line === "both"));
}

export function RoleBadge({ role, profile, code, businessLine }: {
  role: UserRole; profile?: RoleProfile; code?: string; businessLine?: StaffBusinessLine | null;
}) {
  const line = profile?.business_line ?? businessLine;
  const assignedCode = profile?.code ?? code;
  return (
    <div role="group" className="min-w-0 space-y-1.5" aria-label={`${ROLE_LABEL[role]} profile`}>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Badge variant="secondary">{ROLE_LABEL[role]}</Badge>
        {assignedCode && <span className="break-all font-mono text-xs text-text-secondary">{assignedCode}</span>}
      </div>
      {line && <p className="text-xs text-text-secondary">{LINE_LABEL[line]}</p>}
      {profile?.loan_specialty_label && <p className="break-words text-xs text-text-secondary">Specialty: {profile.loan_specialty_label}</p>}
      {!!profile?.teams?.length && <ul className="space-y-1 text-xs text-text-secondary">
        {profile.teams.map((team) => <li key={team.business_line} className="break-words">{LINE_LABEL[team.business_line]} team: {team.name}</li>)}
      </ul>}
    </div>
  );
}

export function OwnRoleBadge() {
  const { session } = useAuth();
  const { me } = useMe();
  const { activeLine } = useLine();
  if (!session) return null;
  const profile = roleProfileFor(me?.roleProfiles, session.role, session.businessLine);
  const customerCode = session.role === "client"
    ? me?.profiles.find((item) => item.businessLine === activeLine)?.customerCode : undefined;
  return <RoleBadge role={session.role} profile={profile} code={customerCode}
    businessLine={session.role === "client" ? activeLine : session.businessLine} />;
}

export function AccountRoleBadges({ user }: { user: components["schemas"]["AdminUserRead"] }) {
  if (!user.roles.length) return <span className="text-sm text-text-secondary">No role</span>;
  return <div className="space-y-3">{user.roles.map((role) => role === "client" && user.client_profiles.length
    ? user.client_profiles.map((profile) => <RoleBadge key={profile.id} role="client" code={profile.customer_code} businessLine={profile.business_line} />)
    : <RoleBadge key={role} role={role} profile={user.role_profiles?.find((profile) => profile.role === role)} />)}</div>;
}
