import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CalculatorIsland } from "@/components/calculators/calculator-island";
import { CalculatorPending } from "@/components/calculators/calculator-pending";
import {
  DashboardBackLink,
  DashboardHeader,
  DashboardPage,
} from "@/features/dashboard/dashboard-ui";
import { CALCULATOR_SLUGS, getCalculator } from "@/lib/calculators/registry";

export function generateStaticParams() {
  return CALCULATOR_SLUGS.map((slug) => ({ slug }));
}

// Just the interactive calculator. The public page's SEO copy, FAQ and lead
// form are for anonymous visitors; a signed-in user only needs the numbers.
// Inputs stay in the URL query (nuqs), as on the public page.
export default async function DashboardCalculatorPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const def = getCalculator((await params).slug);
  if (!def) notFound();

  return (
    <DashboardPage>
      <DashboardHeader
        title={def.h1}
        description={def.cardSummary}
        actions={<DashboardBackLink href="/dashboard/calculators">All calculators</DashboardBackLink>}
      />
      <Suspense fallback={<CalculatorPending />}>
        <CalculatorIsland slug={def.slug} />
      </Suspense>
    </DashboardPage>
  );
}
