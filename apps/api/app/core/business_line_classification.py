"""Closed business-line classification contract for every mapped table.

The shared PostgreSQL enum also contains ``both`` for identity/session claims,
but operational rows must always carry one concrete line.  This registry makes
the exceptions reviewable and lets structural tests reject unclassified future
tables and media purposes.
"""

from __future__ import annotations

import enum

OPERATIONAL_BUSINESS_LINES = frozenset({"loans", "real_estate"})


class ClassificationMode(enum.StrEnum):
    OPERATIONAL = "operational"
    FIXED_LOANS = "fixed_loans"
    FIXED_REAL_ESTATE = "fixed_real_estate"
    GLOBAL_CONTENT = "global_content"
    OPTIONAL_AUDIT = "optional_audit"
    PROFILE_SCOPE = "profile_scope"
    STAGED_REFERRAL = "staged_referral"
    DERIVED = "derived"
    IDENTITY = "identity"
    PLATFORM_CONFIG = "platform_config"


# Keep this exhaustive.  test_business_line_classification.py compares the
# keys with SQLAlchemy metadata so a new mapped table cannot silently inherit
# an accidental classification policy.
TABLE_CLASSIFICATION: dict[str, ClassificationMode] = {
    "agent_applications": ClassificationMode.OPERATIONAL,
    "agent_invite_links": ClassificationMode.DERIVED,
    # Per-account payout destination keyed by auth_user_uuid; no line column.
    "agent_payout_details": ClassificationMode.IDENTITY,
    "agent_profiles": ClassificationMode.OPERATIONAL,
    "attendance_certificates": ClassificationMode.DERIVED,
    # Older attendance days and requests can lack a line snapshot. Their
    # access is evaluated through the staff profile and attendance policies.
    "attendance_days": ClassificationMode.PROFILE_SCOPE,
    "attendance_employment": ClassificationMode.OPERATIONAL,
    "attendance_holidays": ClassificationMode.PLATFORM_CONFIG,
    "attendance_line_holidays": ClassificationMode.OPERATIONAL,
    # A null line repeats on every line (global); otherwise the row line applies.
    "attendance_recurring_holidays": ClassificationMode.GLOBAL_CONTENT,
    "attendance_month_revisions": ClassificationMode.DERIVED,
    "attendance_policies": ClassificationMode.PLATFORM_CONFIG,
    "attendance_requests": ClassificationMode.PROFILE_SCOPE,
    "attendance_rollover_state": ClassificationMode.DERIVED,
    "audit_log": ClassificationMode.OPTIONAL_AUDIT,
    "auth_events": ClassificationMode.IDENTITY,
    "auth_users": ClassificationMode.IDENTITY,
    "bank_loan_type_availability": ClassificationMode.PLATFORM_CONFIG,
    "banks": ClassificationMode.PLATFORM_CONFIG,
    # The banner artwork catalogue itself is line-neutral: a template is a
    # reusable, text-free image plus its category label, and the line-tag lives
    # on the banner row that references it (banners is GLOBAL_CONTENT above).
    # Classifying it OPERATIONAL/GLOBAL_CONTENT would demand a business_line
    # column that carries no meaning for a shared asset.
    "banner_templates": ClassificationMode.PLATFORM_CONFIG,
    "banners": ClassificationMode.GLOBAL_CONTENT,
    "bookmarks": ClassificationMode.FIXED_REAL_ESTATE,
    # Reusable campaign artwork can be scoped to one business line or shared
    # across both, matching banners/offers rather than operational row rules.
    "campaign_media_assets": ClassificationMode.GLOBAL_CONTENT,
    "chat_inquiries": ClassificationMode.DERIVED,  # scope follows the linked lead
    "client_profiles": ClassificationMode.OPERATIONAL,
    "commission_payout_items": ClassificationMode.DERIVED,
    "commissions": ClassificationMode.OPERATIONAL,
    "contact_share_links": ClassificationMode.DERIVED,
    "content_blocks": ClassificationMode.GLOBAL_CONTENT,
    "enquiries": ClassificationMode.FIXED_REAL_ESTATE,
    "fee_cashbacks": ClassificationMode.FIXED_LOANS,
    "field_visibility_config": ClassificationMode.PLATFORM_CONFIG,
    "financial_service_enquiries": ClassificationMode.FIXED_LOANS,
    "financial_product_provider_offers": ClassificationMode.PLATFORM_CONFIG,
    "lead_activities": ClassificationMode.OPERATIONAL,
    "lead_assignment_cursors": ClassificationMode.OPERATIONAL,
    "employee_assignment_cursors": ClassificationMode.OPERATIONAL,
    "leads": ClassificationMode.OPERATIONAL,
    # Rejected lead introductions / referral sign-ups (CS-024): the Agent's
    # line on Agent attempts, NULL on referral attempts (the line is unknown
    # at sign-up, as on a pending referral).
    "lead_intake_attempts": ClassificationMode.OPTIONAL_AUDIT,
    "loan_applications": ClassificationMode.FIXED_LOANS,
    "loan_documents": ClassificationMode.FIXED_LOANS,
    "loan_txn_history": ClassificationMode.FIXED_LOANS,
    "loan_types": ClassificationMode.PLATFORM_CONFIG,
    "mobile_change_requests": ClassificationMode.IDENTITY,
    # CS-025 phone/email changes and their permanent history are identity-wide
    # (one account, both lines), like mobile_change_requests.
    "contact_change_requests": ClassificationMode.IDENTITY,
    "contact_change_history": ClassificationMode.IDENTITY,
    # CS-027 contests: one operational line per contest, copied onto every
    # result row, immutable by trigger.
    "contests": ClassificationMode.OPERATIONAL,
    "contest_results": ClassificationMode.OPERATIONAL,
    # CS-026 India pincode reference list: line-neutral lookup data.
    "pincodes": ClassificationMode.PLATFORM_CONFIG,
    # CS-028 indicative commission rate per loan product: configuration of a
    # loans-only product (loan_types is PLATFORM_CONFIG too); no line column.
    "product_commission_rates": ClassificationMode.PLATFORM_CONFIG,
    "notifications": ClassificationMode.IDENTITY,
    "offers": ClassificationMode.GLOBAL_CONTENT,
    "payouts": ClassificationMode.OPERATIONAL,
    "personalization_preferences": ClassificationMode.IDENTITY,
    "properties": ClassificationMode.FIXED_REAL_ESTATE,
    "property_catalog_types": ClassificationMode.PLATFORM_CONFIG,
    "property_deals": ClassificationMode.FIXED_REAL_ESTATE,
    "property_media": ClassificationMode.FIXED_REAL_ESTATE,
    "property_submission_media": ClassificationMode.FIXED_REAL_ESTATE,
    "property_submissions": ClassificationMode.FIXED_REAL_ESTATE,
    "push_subscriptions": ClassificationMode.IDENTITY,
    "referral_bonus_config": ClassificationMode.OPERATIONAL,
    "referral_codes": ClassificationMode.IDENTITY,
    "referrals": ClassificationMode.STAGED_REFERRAL,
    "refresh_tokens": ClassificationMode.IDENTITY,
    "site_visits": ClassificationMode.FIXED_REAL_ESTATE,
    "staff_profiles": ClassificationMode.PROFILE_SCOPE,
    # Sub Admin–led teams (CS-019): one operational line per team, copied onto
    # each membership so "one team per member per line" is a unique key.
    "staff_team_members": ClassificationMode.OPERATIONAL,
    "staff_teams": ClassificationMode.OPERATIONAL,
    "team_work_notes": ClassificationMode.OPERATIONAL,
    "staff_feature_grants": ClassificationMode.PLATFORM_CONFIG,
    "staff_invite_links": ClassificationMode.DERIVED,
    "sub_admin_access": ClassificationMode.PLATFORM_CONFIG,
    "support_tickets": ClassificationMode.IDENTITY,
    "task_documents": ClassificationMode.DERIVED,
    "task_feedback_media": ClassificationMode.OPERATIONAL,
    "tasks": ClassificationMode.OPERATIONAL,
    "transactions": ClassificationMode.OPERATIONAL,
    "vehicle_arrangements": ClassificationMode.FIXED_REAL_ESTATE,
    # Website drafts and permissions hold platform editorial configuration.
    "website_documents": ClassificationMode.PLATFORM_CONFIG,
    "website_editor_grants": ClassificationMode.PLATFORM_CONFIG,
    "website_revisions": ClassificationMode.DERIVED,
}


MANAGED_MEDIA_CLASSIFICATION: dict[str, tuple[str, str]] = {
    "loan_documents": ("loans", "loan_applications"),
    "property_submission_media": ("real_estate", "property_submissions"),
    "property_media": ("real_estate", "properties"),
    "task_feedback_media": ("derived", "tasks"),
}


def is_operational_business_line(value: str | None) -> bool:
    return value in OPERATIONAL_BUSINESS_LINES
