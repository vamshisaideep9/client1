import { PrivacyContent } from "@/components/help/privacy-content";
import { WebsitePageContent } from "@/components/website-content";
import { getWebsiteContent } from "@/lib/public-website-content";
import { DashboardBackLink, DashboardPage } from "@/features/dashboard/dashboard-ui";
export default async function Page() {
  const published = await getWebsiteContent("page/privacy");
  return (
    <DashboardPage>
      <DashboardBackLink href="/dashboard">Back to dashboard</DashboardBackLink>
      <WebsitePageContent content={published?.content} title="Privacy Policy" fallback={<PrivacyContent dashboard />} />
    </DashboardPage>
  );
}
