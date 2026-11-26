// Product specialty rules for the staff create form, kept framework-free so
// they are unit-tested. The API and the database enforce the same rules; these
// only decide what the form shows.

/** Only Loans or dual-line Telecallers and Officers can specialise in a product. */
export function specialtyAllowed(role: string, line: string): boolean {
  return (role === "telecaller" || role === "employee") && (line === "loans" || line === "both");
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type SpecialtyPrefill = {
  role: "telecaller" | "employee";
  business_line: "loans";
  loan_specialty_id: string;
};

/**
 * `?role=telecaller|employee&product=<id>` (the product staffing page's "Add
 * Telecaller" and "Add Officer" links) opens the create form for a Loans
 * specialist of that product. Any other role is ignored, and a malformed
 * product id leaves the specialty blank.
 */
export function specialtyPrefill(params: Pick<URLSearchParams, "get">): SpecialtyPrefill | null {
  const role = params.get("role");
  if (role !== "telecaller" && role !== "employee") return null;
  const product = params.get("product") ?? "";
  return {
    role,
    business_line: "loans",
    loan_specialty_id: UUID_PATTERN.test(product) ? product : "",
  };
}
