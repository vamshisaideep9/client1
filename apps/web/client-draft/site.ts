// Approved contact details can be supplied here for the review artifact without
// reading deployment .env files. Until then, do not present sample contacts as real.
export { SITE_NAME, TRUST_LINE } from "@/lib/brand";
export const SITE_URL = "https://draft.invalid";
export const SITE_CONTACT = {
  phone: "Phone to be confirmed", phoneHref: "#/contact",
  email: "Email to be confirmed", emailHref: "#/contact",
  hours: ["Business hours to be confirmed"], address: ["Office address to be confirmed"],
};
