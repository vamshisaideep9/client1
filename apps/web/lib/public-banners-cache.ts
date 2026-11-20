// Cache tag on every public banner read (lib/public-banners.ts). The
// revalidate-public-banners Server Action clears it after an Admin approves or
// removes a campaign. Kept in its own module because a "use server" file may
// only export async functions, and the fetch module is server-only.
export const PUBLIC_BANNERS_TAG = "public-banners";
