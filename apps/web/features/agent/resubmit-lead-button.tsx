"use client";

import * as React from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import type { AgentLead } from "@/lib/agent-api";
import type { ApiResponse } from "@/lib/api/client";

// Restarts the Agent's 30-day window on an expired lead whose client hasn't
// registered. The API re-checks eligibility; this button is only shown when
// the lead says it is resubmittable.
export function ResubmitLeadButton({
  leadName,
  onResubmit,
  onDone,
  size = "sm",
  className,
}: {
  leadName: string | null | undefined;
  onResubmit: () => Promise<ApiResponse<AgentLead>>;
  onDone?: (lead: AgentLead) => void;
  size?: "sm" | "default";
  className?: string;
}) {
  const { confirm, confirmDialog } = useConfirm();
  const [pending, setPending] = React.useState(false);

  async function handleClick(event: React.MouseEvent) {
    event.stopPropagation();
    const ok = await confirm({
      title: `Resubmit ${leadName?.trim() || "this lead"}?`,
      description:
        "You'll get a fresh 30-day window. If the customer doesn't respond in that time, the lead expires again.",
      confirmLabel: "Resubmit lead",
    });
    if (!ok) return;
    setPending(true);
    const res = await onResubmit();
    setPending(false);
    if (res.ok) {
      toast.success("Lead resubmitted", { description: "Your 30-day window has restarted." });
      onDone?.(res.data);
    } else {
      toast.error("Couldn't resubmit this lead", { description: res.error });
    }
  }

  return (
    <>
      <Button
        type="button"
        size={size}
        variant="outline"
        className={className}
        disabled={pending}
        onClick={(event) => void handleClick(event)}
      >
        {pending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
        )}
        Resubmit
      </Button>
      {/* Keep dialog events from reaching a clickable table row behind it. */}
      <span onClick={(event) => event.stopPropagation()}>{confirmDialog}</span>
    </>
  );
}
