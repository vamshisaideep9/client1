import { CookiesContent } from "@/components/help/cookies-content";
import { WebsitePageContent } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";
import { DashboardBackLink, DashboardPage } from "@/features/dashboard/dashboard-ui";
export default async function Page() {
  const published = await getWebsiteContent("page/cookies");
  return (
    <DashboardPage>
      <DashboardBackLink href="/dashboard">Back to dashboard</DashboardBackLink>
      <WebsitePageContent content={published?.content} title="Cookies" fallback={<CookiesContent dashboard />} />
    </DashboardPage>
  );
}
