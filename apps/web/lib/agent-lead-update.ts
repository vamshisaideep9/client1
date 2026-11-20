import type { AgentLeadUpdate } from "@/lib/agent-api";

/** An omitted/hidden field must never be submitted as a guessed empty value. */
export function agentLeadUpdate(previous: Record<string, unknown> | null | undefined, notes: string, email: string): AgentLeadUpdate | null {
  const requirement: Record<string, string | null> = {};
  const oldNotes = typeof previous?.notes === "string" ? previous.notes : "";
  const oldEmail = typeof previous?.email === "string" ? previous.email : "";
  if (notes.trim() !== oldNotes) requirement.notes = notes.trim();
  if (email.trim() !== oldEmail) requirement.email = email.trim() || null;
  return Object.keys(requirement).length ? { requirement } : null;
}
