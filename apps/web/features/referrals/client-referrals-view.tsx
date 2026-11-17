"use client";

import * as React from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatPaise } from "@/lib/format";
import { getReferralEligibility, listReferralAttempts } from "@/lib/referrals-api";
import { DASHBOARD_ICONS } from "@/features/dashboard/dashboard-icons";
import { DashboardHeader, DashboardPage, DashboardPanel, MetricCard, MetricGrid } from "@/features/dashboard/dashboard-ui";
import { ROW_ELIGIBILITY_OPTIONS, matchesEligibility } from "@/features/dashboard/eligibility";
import { EligibilitySummaryCards, NotAcceptedList, notAcceptedTabLabel } from "@/features/dashboard/eligibility-ui";
import { FilterSelect } from "@/features/dashboard/filter-select";
import { useEligibility } from "@/features/dashboard/use-eligibility";
import { ReferralCodeCard } from "./referral-code-card";
import { ReferralList } from "./referral-list";
import { useReferrals } from "./use-referrals";

const NOUN = { one: "referral", many: "referrals" };

export function ClientReferralsView() {
  const { my, referrals, loading, error, reload } = useReferrals();
  const eligibility = useEligibility(getReferralEligibility, listReferralAttempts);
  const [filter, setFilter] = React.useState("all");
  const filtered = React.useMemo(
    () => referrals.filter((referral) => matchesEligibility(referral, filter)),
    [referrals, filter],
  );

  return (
    <DashboardPage>
      <DashboardHeader
        title="Referrals"
        description="Share your personal code and track every eligible conversion and reward."
      />

      {loading ? (
        <div className="space-y-6">
          <Skeleton className="h-32 rounded-2xl" />
          <Skeleton className="h-40 rounded-xl" />
        </div>
      ) : error || !my ? (
        <div className="rounded-2xl border border-border bg-card p-8 text-center">
          <p className="text-sm text-text-secondary">{error ?? "Couldn't load your referrals."}</p>
          <Button variant="outline" className="mt-4" onClick={() => void reload()}>
            Try again
          </Button>
        </div>
      ) : (
        <>
          <ReferralCodeCard my={my} />

          {my.eligible ? (
            <MetricGrid>
              <MetricCard label="Referrals" value={my.stats.total} icon={DASHBOARD_ICONS.referrals} />
              <MetricCard label="Converted" value={my.stats.accrued + my.stats.paid} icon={DASHBOARD_ICONS.referrals} />
              <MetricCard label="Bonus accrued" value={formatPaise(my.stats.accrued_amount_paise)} icon={DASHBOARD_ICONS.earnings} />
              <MetricCard label="Bonus paid" value={formatPaise(my.stats.paid_amount_paise)} icon={DASHBOARD_ICONS.transactions} />
            </MetricGrid>
          ) : null}

          {my.eligible ? (
            <EligibilitySummaryCards
              summary={eligibility.summary}
              loading={eligibility.loading}
              noun={NOUN}
              eligibleHint="Can earn or earned a bonus"
              duplicateHint="Already referred by someone else"
            />
          ) : null}

          {my.eligible ? (
            <Tabs defaultValue="referrals">
              <TabsList className="h-auto w-full justify-start overflow-x-auto sm:w-fit">
                <TabsTrigger value="referrals">{`Referrals (${referrals.length})`}</TabsTrigger>
                <TabsTrigger value="not-accepted">{notAcceptedTabLabel(eligibility.total)}</TabsTrigger>
              </TabsList>
              <TabsContent value="referrals" className="mt-4">
                <DashboardPanel
                  title="Referral activity"
                  description="Conversion, reward and eligibility for people who joined with your code."
                >
                  <div className="space-y-3">
                    {referrals.length > 0 ? (
                      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-2 sm:max-w-xs">
                        <FilterSelect
                          label="Eligibility"
                          value={filter}
                          options={ROW_ELIGIBILITY_OPTIONS}
                          onValueChange={setFilter}
                        />
                      </div>
                    ) : null}
                    {/* Keyed by the filter so a new filter starts on page 1. */}
                    <ReferralList key={filter} referrals={filtered} embedded filtered={filter !== "all"} />
                  </div>
                </DashboardPanel>
              </TabsContent>
              <TabsContent value="not-accepted" className="mt-4">
                <DashboardPanel
                  title="Not accepted"
                  description="People who signed up with your code but could not be counted as your referral."
                >
                  <NotAcceptedList
                    attempts={eligibility.attempts}
                    total={eligibility.total}
                    loading={eligibility.loading}
                    error={eligibility.attemptsError}
                    onRetry={() => void eligibility.reload()}
                    emptyDescription="If someone signs up with your code after another person already referred them, it is listed here."
                    label="Referrals not accepted"
                  />
                </DashboardPanel>
              </TabsContent>
            </Tabs>
          ) : null}
        </>
      )}
    </DashboardPage>
  );
}
