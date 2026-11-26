// A Team Manager's member list by product specialty (2026-11-26). Pure so the
// filter rule is unit-tested; the member data comes from /manager/teams.

import type { FilterOption } from "@/features/dashboard/filter-options";
import type { TeamMember } from "@/lib/staff-teams-api";

export const NO_SPECIALTY = "none";

type WithMember = { member: Pick<TeamMember, "loan_specialty_id" | "loan_specialty_label"> };

/** Each specialty held in the team (by label), then "No specialty" when someone has none. */
export function memberSpecialtyOptions(rows: readonly WithMember[]): FilterOption[] {
  const seen = new Map<string, string>();
  for (const { member } of rows) {
    if (member.loan_specialty_id) seen.set(member.loan_specialty_id, member.loan_specialty_label ?? "Unnamed product");
  }
  const options = [...seen.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));
  if (rows.some(({ member }) => !member.loan_specialty_id)) options.push({ value: NO_SPECIALTY, label: "No specialty" });
  return options;
}

export function filterMembersBySpecialty<T extends WithMember>(rows: readonly T[], specialty: string): T[] {
  if (specialty === "all") return [...rows];
  return rows.filter(({ member }) =>
    specialty === NO_SPECIALTY ? !member.loan_specialty_id : member.loan_specialty_id === specialty,
  );
}
