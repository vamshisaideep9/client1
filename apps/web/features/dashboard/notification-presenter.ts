import {
  AlarmClock,
  CalendarCheck,
  CalendarX,
  CarFront,
  ClipboardList,
  Eraser,
  FileCheck2,
  Gift,
  Headset,
  Home,
  Landmark,
  Megaphone,
  PhoneCall,
  ShieldAlert,
  Smartphone,
  Trophy,
  Undo2,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import type { NotificationType } from "@/lib/notifications";

export const NOTIFICATION_TYPE_ICON: Record<NotificationType, LucideIcon> = {
  site_visit_requested: CalendarCheck,
  site_visit_cancelled: CalendarX,
  support_ticket_received: Headset,
  support_ticket_resolved: Headset,
  lead_assigned: PhoneCall,
  lead_released: Undo2,
  agent_lead_expired: Undo2,
  agent_lead_expiry_reminder: AlarmClock,
  task_assigned: ClipboardList,
  loan_status_updated: Landmark,
  property_deal_status_updated: Home,
  referral_converted: Gift,
  document_review_updated: FileCheck2,
  admin_payout_reviewed: Wallet,
  admin_account_action: ShieldAlert,
  admin_retention_purged: Eraser,
  admin_broadcast: Megaphone,
  mobile_change_requested: Smartphone,
  mobile_changed: Smartphone,
  mobile_change_rejected: ShieldAlert,
  contact_changed: Smartphone,
  contact_change_requested: Smartphone,
  contact_change_rejected: ShieldAlert,
  vehicle_arrangement_updated: CarFront,
  campaign_approved: Megaphone,
  campaign_changes_requested: ClipboardList,
  campaign_removed: Eraser,
  contest_submitted: Trophy,
  contest_reviewed: Trophy,
  contest_live: Trophy,
  contest_updated: Trophy,
  attendance_request_updated: CalendarCheck,
  contest_won: Trophy,
  commission_rate_submitted: Wallet,
  commission_rate_reviewed: Wallet,
};

export const NOTIFICATION_TYPE_LABEL: Record<NotificationType, string> = {
  site_visit_requested: "Site visit requested",
  site_visit_cancelled: "Site visit cancelled",
  support_ticket_received: "Support ticket received",
  support_ticket_resolved: "Support ticket resolved",
  lead_assigned: "Lead assigned",
  lead_released: "Lead released",
  agent_lead_expired: "Lead expired",
  agent_lead_expiry_reminder: "Lead expiring soon",
  task_assigned: "Task assigned",
  loan_status_updated: "Loan status updated",
  property_deal_status_updated: "Property deal updated",
  referral_converted: "Referral converted",
  document_review_updated: "Document review updated",
  admin_payout_reviewed: "Payout reviewed",
  admin_account_action: "Account action",
  admin_retention_purged: "Data retention purge",
  admin_broadcast: "Announcement",
  mobile_change_requested: "Mobile change requested",
  mobile_changed: "Mobile number changed",
  mobile_change_rejected: "Mobile change rejected",
  contact_changed: "Contact details changed",
  contact_change_requested: "Contact change requested",
  contact_change_rejected: "Contact change rejected",
  vehicle_arrangement_updated: "Vehicle arrangement updated",
  campaign_approved: "Campaign approved",
  campaign_changes_requested: "Campaign changes requested",
  campaign_removed: "Campaign removed",
  contest_submitted: "Contest awaiting approval",
  contest_reviewed: "Contest reviewed",
  contest_live: "Contest is live",
  contest_updated: "Contest updated",
  attendance_request_updated: "Attendance request updated",
  contest_won: "Contest won",
  commission_rate_submitted: "Commission rate awaiting approval",
  commission_rate_reviewed: "Commission rate reviewed",
};

export function formatNotificationTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMinutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
