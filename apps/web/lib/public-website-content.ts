import { cache } from "react";

import { serverFetchJson } from "@/lib/api/server";
import { websiteKeyPath, type PublicWebsiteContent } from "@/lib/website-content";

const base = "/api/v1/public/website-content";

export const getWebsiteContent = cache(async (key: string) => {
  const result = await serverFetchJson<PublicWebsiteContent>(`${base}/${websiteKeyPath(key)}`, {
    revalidate: 60, expectedStatuses: [404],
  });
  return result.ok ? result.data : null;
});

export const getWebsiteArticles = cache(async () => {
  const result = await serverFetchJson<PublicWebsiteContent[]>(`${base}/articles`, {
    revalidate: 60,
  });
  return result.ok ? result.data : [];
});
