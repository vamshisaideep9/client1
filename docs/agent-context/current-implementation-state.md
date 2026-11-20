# Current implementation state and decision register

Status: **Derived reconciliation and later product amendment**

As of: **2026-08-29**

Code baseline: `14773ae` ([PR #151](https://github.com/brollysolutions/client1/pull/151))

## 1. Purpose and authority

This document records the behavior already implemented in the repository and
the later direction to preserve that work. It is derived from current code,
tests, migrations, recent history, the supplied documents in this directory,
and the explicit 2026-08-06 decision to keep completed behavior unchanged.

The supplied SRS and feature list remain the original historical product
baseline. This register supersedes them only for the specific conflicts
identified below. It does not silently rewrite the supplied source documents.
`SECURITY.md`, current authorization/RLS enforcement, migrations, and later
explicit user decisions continue to govern implementation details.

This is not a claim that every SRS feature is complete. Section 4 separates
genuine open work from document items that the implementation has already
settled.

## 2. Accepted later decisions

### CS-001 — self-registered clients receive both business lines

Every ordinary self-registration creates one authentication user and two
client profiles: one for `loans` and one for `real_estate`. Registration has no
business-line picker, and a dual-line client receives `business_line=both` in
the access-token claims.

This supersedes the SRS and feature-list wording that says a customer selects
Loans, Real Estate, or Both during registration. Because both profiles exist at
account creation, the advisory question about adding a second line later is no
longer applicable to self-registered clients.

Evidence:

- [`apps/api/app/schemas/auth.py`](../../apps/api/app/schemas/auth.py)
- [`apps/api/app/services/auth_service.py`](../../apps/api/app/services/auth_service.py)
- [`apps/api/app/tests/auth/test_register.py`](../../apps/api/app/tests/auth/test_register.py)
- [`apps/web/lib/auth.ts`](../../apps/web/lib/auth.ts)

Compatibility requirement: client-owned RLS remains owner-scoped while every
business record retains one immutable line. Staff and Agent isolation must not
be weakened to implement the dual-line client experience.

### CS-002 — both lines use the established blue visual system

Loans and Real Estate use the same blue dashboard accent. The active line is
communicated by labels, routes, and content rather than by green/amber chrome.

This supersedes the SRS and advisory dashboard-design passages that require a
green Loans surface and amber Real Estate surface. It does not change
business-line authorization or record segregation.

Evidence:

- [`apps/web/app/globals.css`](../../apps/web/app/globals.css)
- [`apps/web/features/dashboard/line-switcher.tsx`](../../apps/web/features/dashboard/line-switcher.tsx)
- [`apps/web/features/dashboard/app-sidebar.tsx`](../../apps/web/features/dashboard/app-sidebar.tsx)
- commit `e2ebece` (`feat(web): blue-only dashboard accent + seamless header + Repeat2 line switch`)

### CS-003 — profile-based identity and scope model is canonical

The current schema does not store every role and line decision directly on a
single conceptual `users` row. It uses one authentication user plus
`client_profiles`, `staff_profiles`, and `agent_profiles`:

- self-registered clients normally hold one profile per line;
- Agents, Telecallers, and Employees are line-scoped;
- Sub Admin is platform-scoped, with artifacts carrying their own line;
- platform Admin authorization requires both the Admin role and platform scope;
- request dependencies install trusted profile and scope context for RLS.

Evidence:

- [`apps/api/app/models/profile.py`](../../apps/api/app/models/profile.py)
- [`apps/api/app/core/deps.py`](../../apps/api/app/core/deps.py)
- [`apps/api/app/services/auth_service.py`](../../apps/api/app/services/auth_service.py)
- [`apps/api/app/services/admin.py`](../../apps/api/app/services/admin.py)
- [`apps/api/alembic/versions/a0b1c2d3e4f5_rls_scope_platform_bypass_to_admin.py`](../../apps/api/alembic/versions/a0b1c2d3e4f5_rls_scope_platform_bypass_to_admin.py)

Conceptual unified-user tables in the supplied designs and ERD are advisory;
they must not drive an identity or RLS migration without a separate approved
design and security review.

### CS-004 — managed property media uses private review and Admin-only approval

Authenticated Clients/Leads, real-estate Agents, and Sub Admins may submit an
existing RERA-registered property with one to ten ordered JPEG, PNG, or WebP
images and up to two reviewer-only PDFs, each no larger than 5 MiB. Only an
active platform Admin may approve or reject; this supersedes the earlier
implementation that also allowed Sub Admin review.

Signed uploads use an owner-bound opaque staging namespace. Submission copies
verified objects into a disjoint server-only canonical private namespace and
verifies them again so a reusable signed upload cannot replace accepted content
or replay an older canonical key. Pending media and all
reviewer PDFs stay private. Approval promotes only verified images to opaque
public property keys; legacy `Property.image` rows remain compatible.

Unreferenced staging objects expire after one hour, rejected private media after
30 days, promoted private image sources after successful publication, and
public media when a listing becomes inactive. Account deletion rejects pending
submissions and deletes their private objects. Video, general Loans/Real Estate
galleries, feedback attachments, content moderation/malware providers, listing
editing, and resubmission remain outside this decision.

Evidence:

- [`apps/api/app/services/property_submissions.py`](../../apps/api/app/services/property_submissions.py)
- [`apps/api/app/models/property_media.py`](../../apps/api/app/models/property_media.py)
- [`apps/api/alembic/versions/f4a5b6c7d8e9_add_managed_property_media.py`](../../apps/api/alembic/versions/f4a5b6c7d8e9_add_managed_property_media.py)
- [`apps/api/app/tests/test_property_submissions_api.py`](../../apps/api/app/tests/test_property_submissions_api.py)
- [`apps/api/app/tests/test_property_media_rls.py`](../../apps/api/app/tests/test_property_media_rls.py)
- [`apps/web/features/real-estate/submit-property-form.tsx`](../../apps/web/features/real-estate/submit-property-form.tsx)

Compatibility requirement: the API owns media authorization and public URL
projection; storage keys never become access-control boundaries. RLS preserves
owner/platform-Admin private access and active-listing public access. Broader
FR-13 requirements remain partial, including malware scanning, image metadata
normalization, and an explicit approved-PDF retention policy.

### CS-005 — Client registration is mobile-first; identity profile details are optional

Ordinary Client account creation requires first and last name, an OTP-verified
mobile, password, and only an optional referral code. Email, gender, income,
occupation, and location are collected after account creation on a skippable
step and remain editable and clearable from Profile settings. Income source is
recorded as `salaried` or `business_income`; the former `net_salary` value is
migrated to `salaried`. No Client capability or business line is gated on
completion.

Location is a labelled search-style field for a manually entered locality/city.
The web app does not request browser geolocation, call a reverse-geocoding
provider, or offer a current-location action. The bounded editable label is sent
to `PATCH /auth/me` only when the user saves the profile.

The shared property omnibox on dashboard home, Explore, category, and Bookmarks
surfaces searches locality, city, PIN, or property name. The Filters sheet keeps
searchable live city/locality controls. Property results, suggestions, and filter
choices come only from the authenticated property API; there is no frontend
sample-location fallback or second catalogue-location selector. The landing
dashboard omits inventory/bookmark/city/category metrics, and property search
never updates the profile. The profile stores one manually supplied readable
value until it is cleared or the account is deleted.

Optional identity-wide values live on `auth_users`; email remains unique when
supplied, and income is represented as a bounded integer-minor-unit source/
amount/period group. Staff provisioning and Agent applications continue to
require email and attach it when a role is added to a mobile-only Client
identity without replacing an address already on file. Registration and initial
reset never use a self-asserted email as proof of mobile control; only an
explicitly selected, previously verified email may receive a reset resend.
Public reset initiation, resend, and verification responses remain neutral for
unknown accounts and absent/unverified email. Email-verification OTPs are bound
to a keyed target fingerprint and a row-locked live address check. The new
fields remain under existing owner/platform-Admin RLS and are cleared during
immediate account deletion.

Evidence:

- [`apps/api/app/services/auth_service.py`](../../apps/api/app/services/auth_service.py)
- [`apps/api/app/models/user.py`](../../apps/api/app/models/user.py)
- [`apps/api/alembic/versions/a6b7c8d9e0f1_align_registration_profile.py`](../../apps/api/alembic/versions/a6b7c8d9e0f1_align_registration_profile.py)
- [`apps/api/alembic/versions/e4b5c6d7e8f9_replace_profile_address_with_location.py`](../../apps/api/alembic/versions/e4b5c6d7e8f9_replace_profile_address_with_location.py)
- [`apps/api/app/tests/auth/test_register.py`](../../apps/api/app/tests/auth/test_register.py)
- [`apps/api/app/tests/auth/test_update_me.py`](../../apps/api/app/tests/auth/test_update_me.py)
- [`apps/web/app/(auth)/register/page.tsx`](../../apps/web/app/(auth)/register/page.tsx)
- [`apps/web/app/(app)/dashboard/settings/page.tsx`](../../apps/web/app/(app)/dashboard/settings/page.tsx)
- [`apps/web/components/profile/optional-profile-fields.tsx`](../../apps/web/components/profile/optional-profile-fields.tsx)
- [`apps/web/features/real-estate/property-search-bar.tsx`](../../apps/web/features/real-estate/property-search-bar.tsx)
- [`apps/web/e2e/registration-profile.spec.ts`](../../apps/web/e2e/registration-profile.spec.ts)
- [`apps/web/e2e/dashboard-navigation.spec.ts`](../../apps/web/e2e/dashboard-navigation.spec.ts)

This supersedes the former mandatory-email registration implementation and
settles FR-3.3/FR-17.2 without changing CS-001 dual-line enrollment or CS-003
profile/RLS scope.

*Amended by CS-025 (2026-11-17):* email is again mandatory, now proven by a
code at registration and added through a blocking step for existing accounts
(enforced per environment), and it can no longer be cleared or edited through
the profile form. The other optional profile fields are unchanged.

*Amended by CS-026 (2026-11-17):* profiles gain an optional pincode whose
place name comes from a built-in list, and an optional one-time "Use my
location" that maps a browser position to the nearest pincode on the server
without storing it.

### CS-006 — vehicle arrangements are a dedicated site-visit workflow

A Client may optionally request one pickup while creating a real-estate site
visit. The request creates a dedicated `vehicle_arrangements` row linked 1:1
to `site_visits`; vehicle logistics are not stored on the visit and are not a
fourth Employee task type. A platform Admin enters vehicle/driver details and
directly assigns an active real-estate Employee. The assigned Employee may
complete or cancel the pickup, while the owning Client follows a read-only
status and receives driver/vehicle details only after assignment.

The lifecycle is `requested → arranged → assigned → completed`, with
non-terminal cancellation. Site-visit cancellation atomically cancels its
active arrangement through a database trigger without granting Clients UPDATE
access to company-managed logistics. Platform-Admin, owning-Client read, and
assigned-Employee policies remain distinct under RLS; audit and notification
payloads exclude pickup locations and contact data.

Evidence:

- [`apps/api/app/models/vehicle_arrangement.py`](../../apps/api/app/models/vehicle_arrangement.py)
- [`apps/api/app/services/vehicle_arrangements.py`](../../apps/api/app/services/vehicle_arrangements.py)
- [`apps/api/alembic/versions/b8c9d0e1f2a3_add_vehicle_arrangements.py`](../../apps/api/alembic/versions/b8c9d0e1f2a3_add_vehicle_arrangements.py)
- [`apps/api/app/tests/test_vehicle_arrangements_api.py`](../../apps/api/app/tests/test_vehicle_arrangements_api.py)
- [`apps/api/app/tests/test_vehicle_arrangements_rls.py`](../../apps/api/app/tests/test_vehicle_arrangements_rls.py)
- [`apps/web/features/admin/vehicle-arrangements-view.tsx`](../../apps/web/features/admin/vehicle-arrangements-view.tsx)
- [`apps/web/features/employee/vehicle-arrangements-view.tsx`](../../apps/web/features/employee/vehicle-arrangements-view.tsx)

This resolves OI-003 and supersedes only advisory passages that proposed
folding fulfilment into `tasks` or attaching logistics directly to a property
deal. A property deal may already reference the same site visit, preserving
workflow history without a duplicate nullable ownership key.

### CS-007 — analytics teams are the existing business lines

For FR-16 reporting, a selected list of Agent profile IDs is the ad hoc Agent
group filter. The Loans and Real Estate business lines are the authoritative
team dimension because Agents are already permanently line-scoped; there is no
separate mutable team-membership entity. Team performance summaries aggregate
the selected Agents by their business line. This resolves the ambiguous
“team” terminology without adding organization management, historical
membership, or a new cross-line access path.

Evidence:

- [`apps/api/app/models/profile.py`](../../apps/api/app/models/profile.py)
- [`apps/api/app/services/reporting.py`](../../apps/api/app/services/reporting.py)
- [`apps/web/features/admin/analytics/report-filter-bar.tsx`](../../apps/web/features/admin/analytics/report-filter-bar.tsx)
- [`apps/web/features/admin/analytics/analytics-view.tsx`](../../apps/web/features/admin/analytics/analytics-view.tsx)
- [PR #150](https://github.com/brollysolutions/client1/pull/150)

Compatibility requirement: report access remains limited to active
platform-Admin sessions, and all selected-Agent and team aggregates keep the
existing business-line predicates and PostgreSQL RLS context.

### CS-008 â€” authenticated personalization is consented and purpose-limited

Client and Agent dashboards may render one live banner per default,
personalized, and action layer. A closed, versioned rule grammar supports user
type, Client journey stage, Agent activity, and bounded geographic circles;
populated dimensions are ANDed and values within one dimension are ORed.
Customer offers remain Client-facing, while Agent benefits and incentives use
the personalized banner layer. Anonymous responses never include personalized
banners or offers with non-empty audience rules.

Activity-based personalization is off until the account owner enables it. The
web app no longer captures or refreshes browser coordinates. A previously saved
coarse personalization point remains removable from Settings and otherwise
expires after 30 days; disabling personalization and account deletion also erase
it. The preference table remains owner-only under RLS, and the existing
authorization-checking one-row database function permits atomic deletion without
giving Admin a read policy. Placements use a private, no-store authenticated
response and validate the caller's active profile and requested business line
before reading content.

Evidence:

- [`apps/api/app/schemas/personalization.py`](../../apps/api/app/schemas/personalization.py)
- [`apps/api/app/services/personalization.py`](../../apps/api/app/services/personalization.py)
- [`apps/api/alembic/versions/c9d0e1f2a3b4_add_authenticated_personalization.py`](../../apps/api/alembic/versions/c9d0e1f2a3b4_add_authenticated_personalization.py)
- [`apps/api/app/tests/test_personalization_api.py`](../../apps/api/app/tests/test_personalization_api.py)
- [`apps/api/app/tests/test_personalization_rls.py`](../../apps/api/app/tests/test_personalization_rls.py)
- [`apps/web/features/dashboard/personalized-placements.tsx`](../../apps/web/features/dashboard/personalized-placements.tsx)
- [`apps/web/features/settings/personalization-settings-card.tsx`](../../apps/web/features/settings/personalization-settings-card.tsx)
- [`apps/web/e2e/personalization.spec.ts`](../../apps/web/e2e/personalization.spec.ts)

Compatibility requirement: no clickstream, impression log, raw or historical
location, IP geolocation, inferred demographic, arbitrary JSON/SQL expression,
or staff targeting is introduced without a separately approved design and
privacy/security review.

*Amended by CS-026 (2026-11-17):* rule version 2 adds pincode and city
targets; a consenting Client's profile pincode (its centroid for circles)
takes precedence over the legacy coarse point.

### CS-009 — v1 payouts use UPI, bank transfer, or manual cheque

**Decision (2026-08-08):** FR-10.3 is interpreted as an outbound disbursement
requirement for cashback, referral bonuses, and commissions. V1 supports UPI
VPA and bank-transfer payouts through RazorpayX plus an audited manual-cheque
workflow. RazorpayX remains the sole automated provider, represented behind an
explicit provider boundary so a later provider does not require redesigning the
payout domain. RuPay/card-number handling, customer checkout, loan-principal or
property-payment collection, a second live provider, configurable routing, and
automatic cross-provider failover are not in v1.

Cheque issuance does not make a payout paid. The payout remains processing
until an authorized Admin records clearance, which emits the recipient-ledger
credit. Voids or bounces fail before settlement; a reversal after clearance
uses the existing compensating-ledger pattern. Only masked cheque references
and a deduplication fingerprint may be retained.

This decision resolves the mixed vocabulary in SRS FR-10.3, where Razorpay is a
provider, UPI is a payment rail, RuPay is a card network, and cheque is an
offline instrument. It does not change FR-10.1/FR-10.2's prohibition on
collecting property payments or loan principal.

**Implementation status:** Complete in
[PR #154](https://github.com/brollysolutions/client1/pull/154). Payout rows
persist an explicit provider; existing VPA and
bank-account rows backfill to RazorpayX, while manual cheques remain approved
until issuance and processing until clearance. Raw cheque references are
reduced to a masked display hint plus a keyed deduplication fingerprint, and
only clearance creates the paid recipient ledger row. Failure and reversal
preserve source-link reconciliation and compensating-ledger behavior.

Evidence:

- [`apps/api/app/services/payments.py`](../../apps/api/app/services/payments.py)
- [`apps/api/alembic/versions/e0f1a2b3c4d6_add_payment_methods.py`](../../apps/api/alembic/versions/e0f1a2b3c4d6_add_payment_methods.py)
- [`apps/api/app/tests/test_payouts_api.py`](../../apps/api/app/tests/test_payouts_api.py)
- [`apps/api/app/tests/test_payouts_live.py`](../../apps/api/app/tests/test_payouts_live.py)
- [`apps/web/features/admin/payouts-view.tsx`](../../apps/web/features/admin/payouts-view.tsx)
- [`packages/contracts/openapi/openapi.json`](../../packages/contracts/openapi/openapi.json)

### CS-010 — Map/GMB integration is removed from the product scope

**Decision (2026-08-09):** Map-based integration, including Google My Business
(GMB) usage, is not part of the current product baseline or future backlog.
FR-18.2 and the aligned feature-list bullet are superseded and must not be
counted as incomplete, deferred, planned, or required for release.

The original supplied SRS and feature list remain unchanged as historical
source documents. This decision changes only their active authority for the
specific Map/GMB requirement; it does not remove address-based properties,
site visits, vehicle pickup locations, or the consented coarse-location
personalization implemented under FR-18.1 and CS-008.

**Implementation impact:** none. No Map/GMB integration exists in the current
code, so no application, API, schema, migration, provider configuration, or
data cleanup is required. Future reintroduction requires a new explicit product
decision and a separate privacy, security, provider, and data-retention review.

### CS-011 — Telecallers and Employees may be provisioned for both lines

**Decision (2026-08-10):** an Admin may provision a Telecaller or Employee for
Loans, Real Estate, or Both. This extends CS-003's line-scoped staff model; it
does not make either role platform-scoped and does not extend dual-line access
to Agents.

A dual-line staff JWT carries `business_line=both`, while every operational API
request resolves to exactly one concrete `loans` or `real_estate` line selected
by the dashboard. The API validates that selector against the signed role and
claim before installing PostgreSQL RLS context. A single-line token cannot use
the selector to expand its access, and assignment/ownership policies continue
to restrict records within the selected line.

Database checks permit `both` only for line-scoped Telecaller and Employee
profiles. Operational records, audit line tags, assignment cursors, leads,
tasks, payouts, and media remain concretely classified as Loans or Real Estate.
This supersedes earlier wording that implied all internal staff must hold only
one line, while preserving the profile-based identity model and all RLS,
maker/checker, audit, and assignment boundaries.

Evidence:

- migration `c5d6e7f8a9b0` and [`apps/api/app/core/deps.py`](../../apps/api/app/core/deps.py)
- dual-line provisioning, assignment, selected-line RLS, and vehicle workflow tests
- [`apps/web/features/dashboard/line-provider.tsx`](../../apps/web/features/dashboard/line-provider.tsx)
- generated OpenAPI and TypeScript contracts

### CS-012 — Main Admin hierarchy and delegated payout requests

**Decision (2026-08-10):** the oldest existing active Admin is migrated as the
single Main Admin. On a clean installation, the first seeded Admin becomes Main
Admin. Only that live Main Admin identity may create additional Admin accounts,
with a maximum of three additional active Admins, or grant/revoke closed staff
features. Main Admin status is database-constrained to an active platform Admin
and is not a caller-controlled token flag. Main Admin deletion is rejected until
a separate, explicit ownership-transfer workflow is approved and implemented.

The first closed feature is `payout_requests`. A granted platform Sub Admin may
search the minimal payout-recipient projection, create payout requests, and
list payout workflow rows. They may not approve or reject a payout, view payout
link reconciliation, or issue, clear, fail, or reverse a manual cheque. Feature
changes increment the target user's session version and revoke refresh tokens,
so a grant or revocation takes effect on the next request and requires a normal
sign-in to obtain fresh signed claims. Payout RLS independently requires the
same feature claim.

Main Admin-created payouts are the only approval-free exception. The service
derives this exception from the live staff row and records an explicit
`primary_admin_standalone` approval audit without fabricating a checker. The
existing recipient/self-payout checks, configured caps, daily serialization,
idempotency/deduplication, provider handling, masked destination storage,
notification, and paid-ledger settlement rules remain in force. A Sub Admin or
additional Admin remains a maker whose payout requires a different Admin.

This decision supersedes the universal maker/checker wording only for a live
Main Admin's own payout. It does not make Sub Admin a general platform Admin,
does not permit arbitrary feature strings, and does not broaden any other RLS
policy or business-line boundary.

Evidence:

- migration `d7f8a9b0c1d2` and the `staff_feature_grants` RLS policies
- [`apps/api/app/services/admin.py`](../../apps/api/app/services/admin.py) and
  [`apps/api/app/services/payments.py`](../../apps/api/app/services/payments.py)
- hierarchy, grant/revocation, payout API/RLS, linked-payout, auth/session, and
  dashboard capability tests
- generated OpenAPI and TypeScript contracts

### CS-013 — property listing authority, owner CRUD, and panorama media

**Decision (2026-08-20):** Clients cannot list properties. Real-estate Agents
may create and manage only their own listings; Sub Admins and platform Admins
may also create listings. Platform Admin retains approval/rejection and broader
operational authority. An owner edit to an approved listing returns the authored
version to review while the last approved catalogue version stays public.
Withdrawal deactivates an approved catalogue row instead of erasing it.

Property MP4 is removed. One optional first-party uploaded equirectangular JPEG
or WebP panorama is supported through the existing private managed-media and
Admin approval lifecycle. Loans video, external tour embeds, 360 video, and
multi-room tours are outside this amendment.

This supersedes FR-7.3 and aligned feature-list wording only where they permit a
Lead/Client to upload property details; FR-13.1/FR-13.3 only for property video;
and CS-004 only where it permits Client submission or excludes listing
editing/resubmission. It preserves real-estate isolation, owner-bound storage,
content verification, reviewer-only documents, RERA review, auditability,
retention, and active-listing public RLS.

Source and approved interpretation:

- [`property-listing-authority-and-panorama-2026-08-20.md`](property-listing-authority-and-panorama-2026-08-20.md)

### CS-014 — Admin-configured product-specific Financial Services forms

**Decision (2026-08-21):** Admin-configured Financial Products and their
versioned, allowlisted application forms are the source of truth for the
authenticated Client dashboard. Lending/funding products retain the loan
lifecycle; Credit Cards and Insurance use quote/enquiry semantics and never
enter sanction/disbursal states. Registered identity fields are server-sourced,
submitted answers are validated against the exact configured version, and
historical submissions retain an immutable schema snapshot.

Lender names and product availability remain Admin-managed reference data and
are not seeded by CS-014. Initial intake also contains no inline KYC/document
upload fields; the existing document workspace remains a separate workflow.

**Implementation status:** Complete in
[PR #211](https://github.com/brollysolutions/client1/pull/211). The
additive migration, typed server validation, generated contracts, Admin form
builder, dynamic Client renderer, loan/enquiry separation, historical
snapshots, RLS ledgers, no-store responses, and account-deletion answer scrub
are implemented and verified. No lender or product-availability seed is part
of this delivery.

This explicitly replaces the previously settled v1 shared-field behavior and
activates the reserved per-product form capability. It does not weaken Admin
authorization, Client ownership, assigned-staff scope, business-line RLS,
account-deletion cleanup, or public catalogue independence.

Source and approved interpretation:

- [`configurable-financial-product-forms-2026-08-21.md`](configurable-financial-product-forms-2026-08-21.md)

### CS-015 — Property-specific listing forms and verified catalogue freshness

**Decision (2026-08-21):** New property intake uses professionally ordered,
code-defined subtype schemas instead of arbitrary detail rows. RERA Registration
Number is optional at intake; applicability and platform-Admin verification are
separate states, and a submitted number alone never produces a verified badge.
Public About/other narrative is bounded plain text and rejects digits, contact
details, and links. Financial Product and lender details expose server-derived
last-updated dates, including relevant Admin availability changes, without
hardcoded lender data or external scraping.

**Implementation status:** Done in
[PR #212](https://github.com/brollysolutions/client1/pull/212). Role, ownership,
media, publication, RLS, audit, retention, historical-record, and Admin-managed
lender boundaries remain unchanged. Fresh evidence includes 183 focused
PostgreSQL passes, migration round-trip and one head, API Ruff/format, all 366
web tests plus lint/typecheck, a 93-page Linux production image, and connected
author/review/public/freshness browser journeys. The full API and browser-suite
baseline limitations are recorded in `feature-status.md`.

Source and approved interpretation:

- [`property-specific-listing-forms-2026-08-21.md`](property-specific-listing-forms-2026-08-21.md)

### CS-016 — Sub Admin-owned Campaign Studio and Media Library

**Decision (2026-08-29):** The Sub Admin team owns banner, authenticated
coupon-offer, banner-template, and reusable campaign-artwork authoring. Platform
Admin does not edit campaign fields or browse the Media Library; Admin previews
the production rendering, approves, requests changes with a note, and may
soft-remove a campaign with a required audited reason. Creator identity remains
immutable provenance while editable work is shared by the Sub Admin team.

Both staff experiences reuse the production homepage, section, sponsor, and
authenticated-dashboard renderers at desktop, tablet, and mobile widths.
Provider logos remain Admin-governed inside Financial Providers, while property,
KYC, loan, task, and other private operational media remain purpose-segregated.

**Implementation status:** Implemented in
[PR #259](https://github.com/brollysolutions/client1/pull/259) on
`codex/20260828-222513-banners-and-offers-are-managed-by-subadmin`; verification
evidence is recorded in the living plan and status ledger. The additive
schema/RLS migration, generated contracts, Campaign
Studio, approval desk, Media Library, serving exclusions, optimistic versions,
maker notifications, usage-safe deletion, and three generated starter assets
implement the decision without changing formal requirement coverage.

Source and approved interpretation:

- [`campaign-studio-media-library-2026-08-29.md`](campaign-studio-media-library-2026-08-29.md)

### CS-017 — same-Agent lead resubmission and Agent-saved payout details

**Decision (2026-11-14, user-approved):** Amends only the named parts of
FR-4.6 and CS-009.

- *Lead name.* An Agent must give the person's name when introducing a lead
  and cannot clear it later.
- *Expiry and resubmit (FR-4.6).* The 30-day Agent window and the return to the
  open Telecaller pool are unchanged. Agents now see the policy ("if the
  customer doesn't respond within 30 days the lead expires; resubmit it after it
  expires") instead of a day countdown. After expiry, **only the Agent who
  introduced the lead** may resubmit it for a fresh 30-day window, and only
  while the client has not registered, the mobile belongs to no account, and
  the lead is neither converted nor closed. Another Agent still cannot attribute
  a mobile whose Agent history ended. Seven days before the window ends, an
  Agent whose client has not registered receives one reminder per window.
- *Payout details (CS-009).* An Agent may save a UPI ID and/or a bank account
  for commission payouts. This is the platform's only store of raw payout
  destinations: values are AES-256-GCM encrypted at rest with a runtime key,
  the Agent sees masked hints only, and a payout maker (platform Admin or a
  Sub Admin with the payout-request grant) may decrypt them only to prefill one
  payout, with every reveal audited. Payout rows still keep only masked hints;
  account erasure removes the saved details.
- *Uploads.* Image and document upload limits are 5 MB everywhere (provider
  logos, banners, campaign images raised from 1, 2 and 4 MB). MP4 video stays
  at 20 MB.

**Implementation status:** Implemented on `feat/agent-dashboard-refinements` in
[PR #334](https://github.com/brollysolutions/client1/pull/334) (mirror #38).
Migrations `f8a0c2e4b6d1` (resubmit-aware expiry trigger, `resubmit_count`,
`expiry_reminder_sent_at`) and `a1b3d5f7c9e2` (`agent_payout_details` with
owner-only RLS and a confined erase function).

Evidence:

- [`apps/api/app/services/leads.py`](../../apps/api/app/services/leads.py) (`resubmit_agent_lead`)
- [`apps/api/app/jobs/remind_agent_lead_expiry.py`](../../apps/api/app/jobs/remind_agent_lead_expiry.py)
- [`apps/api/app/core/field_crypto.py`](../../apps/api/app/core/field_crypto.py)
- [`apps/api/app/services/agent_payout_details.py`](../../apps/api/app/services/agent_payout_details.py)
- [`apps/api/app/tests/test_agent_dashboard_refinements.py`](../../apps/api/app/tests/test_agent_dashboard_refinements.py)

### CS-018 — property listing form refinements, media formats and 360 images

**Decision (2026-11-14, user-approved):** Amends only the named parts of
`property-specific-listing-forms-2026-08-21.md` (field labels, the narrative-safety
rule) and `property-listing-authority-and-panorama-2026-08-20.md` (panorama
count, formats and minimum size). Applies to every lister: Agent, Sub Admin and
Admin share one form.

- *Labels.* "Listing name" becomes "Property name" (same public title field).
  Project listings say "Unit or flat area" and "Flat facing"; the approval
  reference is labelled "Local approval number".
- *Configurations.* 2.5 BHK and 3.5 BHK are added.
- *Ranges.* Unit or flat area and undivided share are From-To ranges; the
  undivided share carries a sq ft or sq yd unit. The existing single values
  remain valid ("From"; legacy UDS reads as sq ft).
- *Approval authority.* GHMC, HMDA, DTCP or GP, or "Other" with a typed name.
  The API keeps accepting any name; the list is a form choice.
- *RERA.* The registration number is shown and sent only when RERA applies.
- *Amenities.* The free amenity list stays, with one-click common amenities.
  Amenities description and About the project move to their own section above
  media.
- *Narratives.* Public descriptions may now include numbers of up to 6 digits;
  a run of 7 or more digits (also when split by spaces, dashes, dots, brackets
  or +) is still rejected as a phone or account number. Links, email and markup
  stay blocked.
- *Media.* Listing photos and 360 images accept JPEG, PNG, WebP and AVIF. A
  listing may have up to ten 360 images (was one), each 2:1 and at least
  1024 x 512 (was 2048 x 1024), at most 25 MP and 5 MB. A failing 360 image now
  gets a specific error instead of "does not match its declared type".

Evidence:

- [`apps/api/app/schemas/property_details.py`](../../apps/api/app/schemas/property_details.py)
- [`apps/api/alembic/versions/c7e9a1b3d5f7_property_media_formats_and_panoramas.py`](../../apps/api/alembic/versions/c7e9a1b3d5f7_property_media_formats_and_panoramas.py)
- [`apps/web/lib/property-submit.ts`](../../apps/web/lib/property-submit.ts)
- [`apps/api/app/tests/test_property_media_constraints.py`](../../apps/api/app/tests/test_property_media_constraints.py)

### CS-019 — Sub Admin managers over Telecaller / Employee teams

**Decision (2026-11-15, user-approved; item 9 of the 2026-11-13 staff
feedback list):** Narrowly amends CS-003. A Sub Admin stays platform-scoped
content staff, but the Main Admin may make one the manager of a team.

- *Team shape.* A team is one operational line plus one member role: all
  Telecallers or all Employees. A Sub Admin manages at most one live team per
  line; a staff member is in at most one team per line (a dual-line member may
  join one team in each line).
- *Who edits.* Only the Main Admin creates, renames, re-manages, staffs or
  archives teams; every platform Admin may view them. Archiving removes the
  members.
- *Manager powers.* Read the team's work in the team's line (leads with client
  name and mobile, applications, enquiries, visits, deals, call outcomes and
  notes; field tasks and their client), each member's analytics, and move open
  work between members of the same team. Every lead-detail view and every move
  is audited. Approvals, payouts, staff creation and pool assignment stay
  Admin-only.
- *Routing is unchanged.* New leads and tasks still round-robin across the
  whole line; teams only supervise.
- *Enforcement.* Manager reach is not a token claim. Read-only RLS policies
  call `team_manager_reaches()`, which reads the team tables live, so removing
  a member, archiving a team, changing its manager or deactivating the Sub
  Admin ends access on the next request. Managers have no UPDATE policy; moves
  run through confined database functions that re-check team, line, open
  status and target.

Evidence:

- [`apps/api/alembic/versions/e4f6a8c0b2d5_staff_teams_and_managers.py`](../../apps/api/alembic/versions/e4f6a8c0b2d5_staff_teams_and_managers.py)
- [`apps/api/app/services/team_manager.py`](../../apps/api/app/services/team_manager.py)
- [`apps/api/app/tests/test_team_manager_api.py`](../../apps/api/app/tests/test_team_manager_api.py)
- [`apps/api/app/tests/test_staff_teams_api.py`](../../apps/api/app/tests/test_staff_teams_api.py)

### CS-020 — Sub Admin managers edit and filter their team's work

**Decision (2026-11-15, user-approved; follow-up to CS-019):** A manager may
change their own team's **open** work and filter it everywhere. Team roster and
team settings stay Main-Admin-only (CS-019 unchanged).

- *Leads.* Set status to working, converted or closed (the Telecaller's own
  choices). Client details stay with their creator (FR-2.8).
- *Tasks.* Change the due date (future only) or cancel with a reason (saved as a
  note). Completing a task stays with the Employee, who records the outcome.
- *Notes.* Append-only notes on a team lead (optional follow-up date) or task,
  read by the reaching manager, the assigned member and platform Admins; the
  member sees them on their own lead or task page.
- *Filters.* A team-wide work list and the member list filter by member,
  status, task type, search, overdue, loan status, last call (incl. not
  called), interest, referral source and "referred by". Team and member
  analytics take the date range, the role filters and a members subset; the
  team overview adds a combined report.
- *Field rules.* Manager views follow the Admin's field rules for the team's
  member role (Telecaller or Employee): a hidden field stays hidden.
- *Enforcement.* Managers still have no UPDATE or INSERT policy; every edit runs
  through a confined definer function that re-checks team reach, line, open
  status and the change. Every edit and note is audited and notifies the
  member.

Evidence:

- [`apps/api/alembic/versions/b2d4f6a8c0e1_team_manager_edits_and_filters.py`](../../apps/api/alembic/versions/b2d4f6a8c0e1_team_manager_edits_and_filters.py)
- [`apps/api/app/tests/test_team_manager_edits_api.py`](../../apps/api/app/tests/test_team_manager_edits_api.py)

### CS-021 — One filter system, Settings by role, and staff self-service limits

**Decision (2026-11-16, user-approved stakeholder feedback, batch A):**

- *Filters.* Every dashboard filter uses one control: unfiltered it reads the
  field name and its first option is "All"; secondary filters sit behind
  "More filters (n)" with removable chips; paired dates read From / To. Lead
  source options are Direct lead / Referred by agent / Referred by client.
  Lead lists open New > Assigned > Working > Converted > Closed > Released,
  then next follow-up; closed and rejected loan applications sink.
- *Settings by role.* Client and Agent keep an editable profile and Delete
  account; Admin keeps an editable profile and Delete account. Telecaller,
  Employee and Sub Admin (including team managers) see their profile
  read-only, with no Save, no personalization card and no Danger zone; name
  and contact changes go through an Admin (the request flow is a later
  batch). `PATCH /auth/me` and `DELETE /auth/me` return 403 for those roles.
- *Personalization (amends CS-008).* The consent preference and the coarse
  location endpoints are Client-only. Agents lose the consent switch, so
  banners targeted by Agent activity signals no longer match any Agent;
  role-only Agent banners still do. An additive migration erases every
  stored preference that does not belong to a Client. Placements keep serving
  Client, Agent, Employee and Telecaller.
- *Account deletion (amends SRS 5.1 self-deletion for staff).* Self-service
  deletion stays for Client, Agent and Admin (Main Admin protection
  unchanged). Telecaller, Employee and Sub Admin accounts are removed through
  the existing Admin account-removal action.
- *Analytics.* My analytics opens on the previous calendar month and labels
  its KPI tiles with the period; the Agent "Commission by status" breakdown
  leaves out cancelled commissions (they stay in commission history).

CS-005's profile rules are unchanged for Clients. Evidence is listed in
`feature-status.md` under Batch A.

### CS-022 — Agent commission history, payout trail, lead history and cancelled cheque

**Decision (2026-11-16, user-approved stakeholder feedback, batch B; both
lines, Agents stay line-scoped):**

- *Commission summary.* The Agent sees Total / Pending / Paid and the amount
  paid in the previous calendar month (IST), labelled with that month
  ("Commission paid · Oct 2026"). Totals cover every commission; filters only
  narrow the history rows. Cancelled commissions stay in the history (CS-021).
- *Commission history.* Each commission shows its client (the Agent's own lead
  name, under the existing Agent "Lead name" rule), lead, product or property,
  bank, deal status, deal amount and paid date, with status, deal type,
  product, bank, property category, amount, date and search filters.
- *Transaction detail.* A commission transaction shows the payout method with
  its masked hint, when it was requested, approved, issued (cheque), paid or
  reversed, who requested and who approved it (name and role), and the one
  commission it paid. Each payout pays exactly one commission today; bundled
  payouts are a separate money-layer feature.
- *Lead history.* Only for a lead the Agent introduced, on their line:
  applications, service enquiries, property deals, enquiries, site visits,
  call outcomes with telecaller notes, and a status timeline. Status reasons,
  rates, fees, form answers, contact details and messages are not shown.
- *Field rules.* New Agent rules, all default visible: telecaller call notes,
  telecaller names, loan and deal amounts, payout staff names. The Admin can
  switch each off; existing notes become visible to Agents retroactively
  while the rule is on.
- *Enforcement.* The reach is not a table policy. Three SECURITY DEFINER
  read functions re-check the Agent context and return projected columns
  only, because a new SELECT policy would also widen the RLS-only request
  routes that return full loan applications and deals. Payouts and the audit
  log stay Admin-only.
- *Cancelled cheque.* Optional, JPEG/PNG/PDF up to 5 MB, attached to saved
  payout details; replacing or removing the bank account removes it. Payout
  makers (Admin, or a Sub Admin with the payout-request grant) can open it;
  every view is audited. It is erased with the account.

Evidence is listed in `feature-status.md` under Batch B.

### CS-023 — Filters by product, property, status, transactions and earnings

**Decision (2026-11-17, user-approved stakeholder feedback, batch C; both
lines):**

- *Every dashboard.* Lead lists (Telecaller leads, Employee tasks, a
  manager's team work) and analytics (My analytics, team analytics, Admin
  reports) filter by financial product, bank and loan status on the loans
  line, and by property category, subtype and deal status on the real estate
  line. Product and property filters describe one application or one deal:
  "Home loan at HDFC, sanctioned" matches a lead only when one application is
  all three. Options come from the active catalogue plus any product or bank
  already on a loaded row.
- *Telecaller transactions.* The Telecaller list (and a Telecaller team's
  work list) filters by the loan transactions the Telecaller recorded: has a
  transaction or none, date range, bank and amount range, one transaction
  matching all of them. Bank options are the catalogue's names plus any name
  already entered. Employees and Agents get no transaction data.
- *Earnings.* Agent My analytics adds product, bank, loan or deal status,
  property, commission status and a commission amount range; every filter
  narrows both the leads and the commissions (a lead filter keeps the
  commissions on those leads; a commission filter keeps the leads that have
  one). Telecaller analytics take an amount range on the requested loan amount
  or quoted price, while the Admin shows that amount to Telecallers.
  Employees have no amount filter.
- *Field rules.* The Admin's Telecaller rules for transaction bank, amount and
  date hide those parts of the transaction data (and the matching filters)
  for Telecallers and their managers; application and deal amounts never
  reach the browser through the lists.
- *Enforcement.* The facts come from the two existing confined readers
  (`lead_list_signals`, now also for an Agent's own introduced leads, and
  `team_lead_signals`), which re-check the caller; no table policy or grant
  changes. A filter the role, line or field rules do not allow is refused
  (422), never ignored.

Evidence is listed in `feature-status.md` under Batch C.

### CS-024 — Lead and referral eligibility

**Decision (2026-11-17, user-approved stakeholder feedback, batch D; both
lines):**

- *One panel each.* Clients refer by code and never introduce leads; Agents
  introduce leads and cannot refer (FR-9.1). The Client Referrals page shows
  referral eligibility and the Agent Leads page shows lead eligibility, each
  as Eligible / Not eligible / Duplicate with a reason.
- *Accepted rows.* An Agent lead is Eligible until its 30-day attribution
  window expires; an expired lead is Not eligible ("Your 30-day window
  ended") and becomes Eligible again if the Agent resubmits it. A referral is
  Not eligible when it was voided or refused a bonus: self-referral, the
  referrer no longer an active client, below the minimum conversions, or the
  bonus limit reached. The last two are stored as "converted" without a
  bonus but still read as Not eligible. Pending, converted (including no
  active bonus rule), accrued and paid referrals are Eligible.
- *Rejected attempts, from release onward (no backfill).* An Agent
  introduction turned away because the number is registered, on another
  Agent's or line's enquiry, or already being worked is a Duplicate
  ("Already registered or linked to an existing enquiry"); re-introducing the
  Agent's own expired lead is Not eligible ("Your earlier lead for this number
  expired"; resubmission stays the way back). A sign-up with a Client's code
  for someone another Client already referred is a Duplicate for that Client;
  a self-referral is Not eligible. An unknown code has no owner and stays only
  in the registration event. The Agent's 409 response is unchanged, and no
  reason says whose the existing record is.
- *Privacy.* An attempt keeps the last four digits and a keyed fingerprint of
  the number (HMAC under the server secret, purpose-bound), never the number.
  A repeat of the same attempt within 24 hours is stored once. Only the owner
  can read it (no Admin view was asked for, so none is granted); nothing but
  the capture and referral
  services can write it; it is erased with the owner's account, whether the
  owner deletes it or an Admin removes it. The other person's own account
  deletion does not erase the owner's masked row.
- *Counts.* Eligible counts accepted eligible rows; Not eligible counts
  accepted rows a rule excludes plus attempts turned away by a rule; Duplicate
  counts duplicate attempts. "Not accepted" lists every recorded attempt.
- *Agent lead filters.* The Agent Leads list also filters by status and, from
  Batch C's facts, by product, bank and loan status (loans) or property
  category, type and deal status (real estate).

Evidence is listed in `feature-status.md` under Batch D.

### CS-025 — Mandatory email, self-service contact changes and contact history

**Decision (2026-11-17, user-approved stakeholder feedback, batch E; amends
CS-005's optional email and the support-only mobile change):**

- *Email is mandatory.* Registration requires an email proven by a code;
  every existing account without a verified email is held on a blocking
  "Add your email" step after sign-in until it adds and verifies one. Email
  can no longer be cleared, and `PATCH /auth/me` no longer edits it.
  Enforcement is behind the server setting `EMAIL_REQUIRED_ENFORCED` (off by
  default) and is switched on per environment only after email delivery has
  been proven there end to end. While it is on, every endpoint answers 403
  for such an account except `/auth/me`, the add/verify email endpoints, a
  staff contact-change request, account deletion, logout, refresh and
  password change.
- *Adding an email* needs the current password and a code sent to the new
  address. A Telecaller, Employee or Sub Admin may only verify the address an
  Admin set; a different one goes through a contact-change request. An
  address verified on another account is refused (after the code, so the
  check reveals nothing to someone who does not control it); an unverified
  copy elsewhere is released to the proven owner.
- *Self-service change (Client, Agent, Admin).* Current password, a code to
  the current number or email, the new value, a code to the new value, then
  one atomic update: the old value is replaced, the session version is
  bumped, every refresh token is revoked and push subscriptions are removed.
  Notices go in-app and by email to the old and the new address (an email
  change) or to the verified email (a phone change: there is no SMS channel).
  Phone and email are never changed together: one active change per account,
  and an open lost-number request also blocks a new change (409).
- *Lost number.* The public `/change-mobile` request flow (two Admins, proof
  category only, no upload) is unchanged and linked from Settings.
- *Staff requests.* Telecallers, Employees and Sub Admins (managers included)
  request a phone or email change; the new value is proven by a code; one
  platform Admin, never the requester, approves (applied like the
  self-service change) or rejects with password re-entry.
- *History.* `contact_change_history` keeps every completed change (field,
  old value, new value, method, proof category and PII-free reference,
  approver, time) permanently, readable by a platform Admin only (the account
  holder cannot read it) and erased only with the account. Audit and auth
  events carry ids, field and method, never the values. Change requests keep
  the raw new value only while active (a database CHECK clears it on every
  terminal status), as mobile-change requests already do.

Evidence is listed in `feature-status.md` under Batch E.

### CS-026 — Profile pincode, place names, one-time GPS and location-targeted campaigns

**Decision (2026-11-17, user-approved stakeholder feedback, batch F; amends
CS-005's "no browser geolocation / manual location only" and CS-008's
location dimension; "Does not fit" item 10 of the batch plan):**

- *Profile pincode.* Every profile may carry an optional six-digit Indian
  pincode (first digit 1–9; CHECK on `auth_users.pincode`). Clients are the
  target; Agents and Admins may also set it through `PATCH /auth/me`;
  Telecallers, Employees and Sub Admins stay read-only (CS-021). It is
  cleared with the account. A well-formed pincode missing from the reference
  list is accepted without a place name. The existing free-text location
  field is unchanged.
- *Place name.* Area, district and state come from a built-in reference list
  (`pincodes`, one row per pincode with a centroid), never stored as free
  text with the profile. Source: GeoNames India postal codes, CC BY 4.0,
  attributed in the app; provenance, normalisation and checksum are in
  `apps/api/app/data/SOURCES.md`. No outside map or geocoding service is
  called.
- *"Use my location".* Optional. The browser asks for the position once, the
  server maps it to the nearest pincode centroid (Haversine, within 100 km,
  India bounding box only) and returns the pincode and place name. The
  position is used once in memory and never stored, logged, audited or sent
  to the database; the person sees the suggestion and saves it like any
  profile field. Telecallers, Employees and Sub Admins cannot use it.
- *Location-based campaigns.* `AudienceRules` version 2 adds `pincodes` and
  `cities` (a city is a district + state from the reference list) beside the
  version-1 circles; version-1 rules keep matching unchanged. Circles,
  pincodes and cities form one "where" dimension (any match counts), ANDed
  with the other dimensions. Location matching uses the Client's profile
  pincode — its centroid for circles — only while the Client has BOTH
  personalized content and the separate, revocable location consent
  ("Offers for your area", CS-008's `location_enabled`) on. That location
  consent can now be given without capturing any device point
  (`PUT /personalization/location/consent`, needs personalized content and a
  saved profile pincode); revoking it (`DELETE /personalization/location`)
  or turning personalized content off stops every pincode, city and circle
  match at once, and turning personalized content back on does not restore
  it. Precedence: when a profile pincode with a centroid exists it is the
  Client's location for circles; otherwise a still-valid legacy coarse point
  (same consent, 30-day retention) is used. Pincode and city targets match
  the profile pincode only. Pincode and city targets need a Client-only
  audience, and every targeted pincode or city must exist in the reference
  list.
- *Privacy notice.* Updated for the pincode and one-time GPS use; flagged
  for legal review before release.

CS-008's compatibility requirement still holds: no clickstream, raw or
historical location, IP geolocation or inferred demographic is introduced.
Evidence is listed in `feature-status.md` under Batch F.

### CS-027 — Contests: Sub Admin-authored, Admin-approved incentive contests

**Decision (2026-11-17, user-approved stakeholder feedback, batch G; new
module; "Does not fit" items 6, 11, 12 and 13 of the batch plan):**

- *Who.* A Sub Admin creates a contest for one line and one audience:
  Agents, Telecallers, Employees, or the Telecaller or Employee teams that
  Sub Admins manage (a "manager" is a Sub Admin who manages a team; there is
  no manager role). A platform Admin who is not the maker approves or
  rejects it (maker ≠ checker in the service and by database CHECK);
  rejected contests are edited and resubmitted. A contest cannot be
  submitted or approved once its start date has passed.
- *Rules.* A versioned, closed criteria grammar (`schemas/contests.py`):
  loan cases (products, banks, per-case amount range, counted stage
  submitted / sanctioned / disbursed, case count at least / at most, total
  amount at least) or property deals (categories, types, sale / rent,
  cities, per-deal value range, counted stage site visit done / booked /
  agreement signed / closed, deal count, total value), staff activity
  (Telecallers: calls, connect rate with a minimum number of calls,
  follow-ups kept on time, site visits completed on held leads; Employees:
  tasks completed, tasks completed on time, site visits completed), and
  eligibility (minimum tenure; KYC verified for Agents; an active profile
  on the contest's line always). Dimensions from the other line or for the
  wrong audience are refused. "5 cases or fewer" is an optional at-most
  count that is only accepted beside an at-least count, since an at-most
  rule alone rewards doing less.
- *Win mode and prize.* Per contest: `threshold` (everyone who meets every
  target) or `top_n` (the N best qualifying participants with a result
  above zero; a tie at the cut-off is kept whole). Fixed prize per winner;
  team contests have a combined team target and pay the managing Sub Admin
  a manager prize and each member whose own contribution reaches the member
  minimum a member prize. An optional budget cap pays winners in rank order
  and leaves out the first group of equal achievers that would cross it
  (and everyone below).
- *Credit.* Agents: leads they introduced (at disbursed / closed this is the
  commission-eligibility predicate). Telecallers: leads they hold when
  scored — only the current assignee is stored, so a reassigned lead counts
  for its current holder, and only if they logged a call on it before the
  case reached the counted stage (a manager reassigning a counted lead moves
  no credit). Employees: leads where they completed a task at or
  before the moment the case reached the counted stage (database-stamped
  completion time; open, later or reassigned-later work earns nothing).
  Teams: their current members, a shared case counted once; a team managed
  by the contest's own maker takes no part. A case counts when it
  reached the counted stage inside the contest dates (new stage markers on
  loan applications and property deals); its "true amount" is read live at
  that stage (requested when submitted, sanctioned once sanctioned or
  disbursed, a deal's quoted price or its listing price before a quote).
- *Lifecycle.* Standings are computed on read while a contest runs; a
  scheduler job takes approved contests live on their start date and ends
  them after their end date, snapshotting the standings. After the end the
  Admin reviews (and may recalculate) the standings and confirms winners.
- *Paying prizes.* Agent prizes go through the existing Payouts
  maker-checker as a `contest_reward` payout — one per result, never
  approval-free (the Main Admin standalone exception does not apply), and
  within the budget cap. Staff have no saved payout destination and staff
  incentives normally run through payroll, so staff prizes are recorded and
  marked paid by an Admin with an audit entry. Tax treatment of prizes needs
  the accountant's confirmation before release.
- *Visibility.* Participants see only the contests for their role and line,
  their own result, and a leaderboard of display name (first name and last
  initial), rank and achieved value; the Admin can hide other participants'
  names or amounts per role through field visibility. Managers see their
  team's progress and members.

Evidence is listed in `feature-status.md` under Batch G.

### CS-029 — Telecaller loan specialties and scoped staff identifiers

**Decision (2026-11-20; Round 2 Batch 3):** Admins may optionally assign an
active loan product as the specialty of a Loans or dual-line Telecaller, on
provisioning or later account editing. Existing staff start unspecialised.
For a known active loan product, automatic assignment tries same-line/dual-line
specialists, then unspecialised Loans Telecallers, then all eligible Telecallers.
Each actual candidate pool rotates independently. Unknown/ambiguous products use
the all-eligible pool. Real Estate keeps its line rotation. Current assignments
are preserved; sticky Agent resubmission still precedes specialty routing.

Task participants may read their actual counterpart's name and assigned code,
without counterpart phone/email or a staff-directory grant. Own profile metadata
includes staff/Agent codes, specialty and each active team's name/line, including
both teams for dual-line staff. Admin directory metadata is batched; manager
rosters remain limited to their reached staff. Web surfaces reuse the approved
operational design and display server-assigned codes rather than deriving IDs.

API work on `feat/staff-specialty-routing-api` has complete segmented evidence
for all 2,920 tests, a populated migration rollback, generated contracts and the
compatible web gate; exact results and resolved test failures are in the living
plan/status. Delivered for review as [upstream #390](https://github.com/brollysolutions/client1/pull/390)
and [mirror #91](https://github.com/vamshisaideep9/client1/pull/91). Assignment must be quiesced while the
API and single scheduler move together to the new cursor key. No payout, attendance,
public-page or dependency scope is included in this decision.

Hosted verification exposed a shared-catalogue test fixture assumption, not a
routing change: duplicate Personal Loan labels correctly use the all-staff
fallback. The test now creates a unique product for its public-label assertion;
a duplicate-label reproduction and the full 20-test routing file pass after
the correction. Inherited Python dependency-audit findings remain a failed gate.

The web slice implements specialty create/edit with safe retry/clear and delayed
save handling, shared assigned-code/specialty/team badges and task counterparts.
Its unchanged runtime passes lint/typecheck, 1,119 unit tests, the 118-page Node 22
production build, eight original-font comparisons and all 26 production-browser
journeys together. Seven inspected synthetic screenshots and review limits are
in `apps/web/e2e/review/staff-specialty/README.md`. No dependency, new motion,
public route or authorization expansion is included. Web delivery links are in
the living plan/status; Batches 4-6 remain unstarted.

### CS-028 — Agent lead form fields, sticky resubmission, bulk submit and product commission rates

Web slice (2026-11-20, `feat/agent-lead-intake-web`, parent API `e70b18c3`):
Agent email/property type with optional matching listing, approved rate/note,
resubmission filters/badges, local CSV/XLSX templates and bounded parsing,
row preview and valid-row submission, formula-safe result download and mobile
result cards. Admin/Sub Admin rate management includes maker/checker review and
a per-product commission tab; per-deal suggestions remain editable. Email-only
edits preserve untouched/hidden notes. The commission tab has its own save action,
with error/retry preserving inputs. No dependency or API change in this slice.
The unchanged runtime passes 1,113 unit tests and the 118-page Node 22 build;
the final combined production-browser run passes all 11 scenarios with synthetic
API mocks. Post-restack lint/typecheck and runtime/API/contract identity checks
pass. Web [upstream #389](https://github.com/brollysolutions/client1/pull/389)
merged as `78567697`; [mirror #90](https://github.com/vamshisaideep9/client1/pull/90)
remains open against `main`, refreshed to that merged history. API upstream #388
merged as `66caddde` and mirror #89 remains open at that merged history. These
states were rechecked while continuing Batch 3. Hosted mirror jobs were blocked
by billing/spending restrictions at Batch 2 delivery. Batch 3 continues from this
merged baseline.

**Decision (2026-11-19, client-reported batch 2 "Agent leads"; both lines;
amends CS-017's resubmission and the FR-8.1 commission entry; the detailed
Round 2 brief and stacked-PR delivery were confirmed on 2026-11-20):**

- *Lead form.* An Agent's lead is name, mobile, an optional email, the
  requirement (loans: a loan product; real estate: a property type, with or
  without a specific listing, which must then agree) and a description (the
  existing notes). The email and property type are stored under the lead's
  requirement, owned by the Agent in the detail-ownership ledger; the Agent
  may change or remove the email and notes while the lead is editable; the
  product, listing and property type are fixed at introduction.
- *Input compatibility.* The optional top-level `email` and the existing
  nested `requirement.email` normalize into that one stored key. Matching
  nonblank values are accepted; conflicting ones are rejected. A legacy
  update carrying a valid name and `requirement: null` clears owned notes
  only, preserving email and the fixed interest fields; another creator's
  notes remain protected and cause the whole update to fail.
- *Email deletion.* Account deletion erases the person's lead email from
  active and historical journeys selected by their verified mobile or
  Client profile. Deleting a referring Agent does not erase another
  person's contact. The existing financial-record retention window stays
  separate; a deleted person's lead email is erased immediately, rather
  than retained until a financial purge.
- *Who reads a lead's requirement.* One allowlist for every read: the
  originating Agent sees keys attributed to them in the ownership ledger.
  Current/new claims preserve other creators' ownership and do not expose
  their input. The old backfill attributes known fields by recorded Agent
  origin; a public row already claimed before that ledger can contain earlier
  merged input with that same descriptor. No accepted/claim per-key audit can
  reconstruct those indistinguishable fields safely. The legacy regression
  verifies the original backfill and subsequent claims, rather than proving
  authorship of every pre-ledger claimed key. The assigned Telecaller sees every known key,
  the email included, behind the existing Telecaller "Requirement details"
  field rule (there is no separate email rule); a platform Admin's lead
  details show notes, the resolved labels and the email; a Client's lead
  details never show the email; Employees, Sub Admin team views and the
  Agent's lead history carry no requirement.
- *Resubmission goes back to the same Telecaller.* Every path that clears
  a lead's Telecaller (the 30-day expiry, the repair of an ineligible
  assignee, an Admin release) remembers that Telecaller. When the Agent
  resubmits an expired lead that is still unassigned, it goes straight back
  to them while they are an active Telecaller on the lead's line (or both
  lines); otherwise round-robin assignment applies as before. A lead the
  open pool already gave to another Telecaller before the resubmission
  keeps that Telecaller (a lead being worked is not interrupted). Agent,
  Telecaller and Admin lead lists show how often and when a lead was
  resubmitted.
- *Bulk submit.* An Agent uploads a spreadsheet the browser reads (at most
  200 rows: S.No, name, mobile, email, requirement, description). A
  check-only pass validates the rows (Indian mobile formats, repeated
  numbers, product / property type on the Agent's own line) without looking
  anything up; the real submit treats every row exactly like a single
  introduction and reports each row (created, already yours, duplicate,
  not eligible, repeated in the file, invalid, temporarily unavailable).
  Limited to 5 submits and 30 checks per Agent per hour; one audit entry
  per submit with counts only.
- *Commission rate per loan product.* A Sub Admin or a platform Admin
  enters an indicative commission for a loan product: a percent of the
  loan amount or a fixed rupee amount, plus an optional short note. A Sub
  Admin's entry waits for a platform Admin who did not make it (approve,
  or reject with a note; the maker may withdraw it, and a new proposal
  replaces their own earlier one); a platform Admin's own entry applies at
  once as standalone entry with no checker or review timestamp. Any recorded
  checker must differ from its maker. A platform Admin sees all workflow rows;
  a Sub Admin sees approved rates and their own workflow rows only. Loans
  Agents and eligible loans/both-line Telecallers and Employees have approved-
  only RLS reads; the management API remains Admin/Sub Admin and the Agent
  endpoint remains Agent-only. Rates are never public. The per-deal commission
  is still entered by the Admin, now
  pre-filled with the rate applied to the sanctioned amount (the requested
  amount when none was sanctioned) or the fixed amount.

Evidence is listed in `feature-status.md` under Batch 2. API review: [upstream #388](https://github.com/brollysolutions/client1/pull/388),
[mirror #89](https://github.com/vamshisaideep9/client1/pull/89), both against `main`. Final API verification
at `5c5c4467` passes all 2,884 tests with no failures/errors/skips and one
Alembic head. The web slice follows; this session stops after Batch 2, with
Batches 3–6 reserved for a new session.

## 3. Previously open items settled by current behavior

The following entries may still be labelled “open,” “assumed,” or “pending” in
the supplied designs. Preserve the implemented behavior unless a later decision
explicitly changes it.

| Topic | Current behavior | Evidence |
| --- | --- | --- |
| Telephony and number masking | Integrated telephony, recording, and masking are outside v1. Assigned Telecallers use the visible number and device dialer. | SRS v1.2 §5.2/§5.7 and feature-list v1.2 revision note |
| Loan-type custom fields | Superseded by CS-014: Admin-configured versioned product forms are now approved for the authenticated Client dashboard. | [`configurable-financial-product-forms-2026-08-21.md`](configurable-financial-product-forms-2026-08-21.md) |
| Agent lead editing cutoff | The originating Agent may edit an unassigned lead; assignment to a Telecaller locks further Agent edits. | [`services/agent.py`](../../apps/api/app/services/agent.py), [`test_agent_api.py`](../../apps/api/app/tests/test_agent_api.py) |
| Telecaller field tasks | A Telecaller may raise a `document_collection` task for an assigned lead; the service assigns it to an active same-line or dual-line Employee by durable round robin, with scheduled no-capacity retry and inactive-assignee repair. Admin sees the relationship read-only. | [`api/v1/telecaller.py`](../../apps/api/app/api/v1/telecaller.py), [`services/telecaller.py`](../../apps/api/app/services/telecaller.py), [`services/employee_assignment.py`](../../apps/api/app/services/employee_assignment.py), [`test_employee_auto_assignment.py`](../../apps/api/app/tests/test_employee_auto_assignment.py) |
| Document verification owner | A platform Admin verifies task and loan documents. The collecting Employee cannot self-verify. | [`api/v1/document_verification.py`](../../apps/api/app/api/v1/document_verification.py), [`models/task.py`](../../apps/api/app/models/task.py) |
| Background-check representation | A task has one outcome: `clear`, `flagged`, or `inconclusive`; structured sub-checks are not part of the current model. | [`models/task.py`](../../apps/api/app/models/task.py), [`schemas/employee.py`](../../apps/api/app/schemas/employee.py) |
| Website content approval | The staff Website content UI is intentionally removed for both Admin and Sub Admin. Existing content blocks and public rendering remain; at the retained backend boundary, Sub Admin content blocks publish directly with no Admin approval gate. | [`api/v1/content.py`](../../apps/api/app/api/v1/content.py), [`test_content_blocks_api.py`](../../apps/api/app/tests/test_content_blocks_api.py), [`nav-items.ts`](../../apps/web/features/dashboard/nav-items.ts) |
| Banner precedence | Public banners sort by highest `priority`, then oldest `created_at`, then stable ID. | [`services/public_catalog.py`](../../apps/api/app/services/public_catalog.py), [`test_public_banners.py`](../../apps/api/app/tests/test_public_banners.py) |
| Client status reasons | The API exposes `status_reason`, and the client loan UI renders it verbatim when present. | [`schemas/loans.py`](../../apps/api/app/schemas/loans.py), [`apps/web/lib/loans.ts`](../../apps/web/lib/loans.ts), [`loans-applications.tsx`](../../apps/web/features/dashboard/loans-applications.tsx) |
| Referral payout execution | Sub Admin manages bonus configuration; creating the actual referral payout is restricted to platform Admin. | [`api/v1/referral_bonus.py`](../../apps/api/app/api/v1/referral_bonus.py), [`api/v1/referrals.py`](../../apps/api/app/api/v1/referrals.py) |
| Agent lead expiry | Agent attribution has a fixed 30-day first-attribution deadline with converted/closed exclusions, idempotent scheduled release, audit, notifications, RLS denial, and Agent history/countdown. CS-017 (2026-11-14) adds same-Agent resubmission, a 7-day reminder, and policy copy in place of the countdown. | [PR #144](https://github.com/brollysolutions/client1/pull/144), [`services/lead_expiry.py`](../../apps/api/app/services/lead_expiry.py) |
| Client registration and optional profile | Client registration is mobile-first; demographic/income/location details are optional, skippable, editable, clearable, and never gate account use. Location is entered manually through a search-style field; the web app does not request browser geolocation. CS-025 (2026-11-17) makes email mandatory and code-verified (enforced per environment by `EMAIL_REQUIRED_ENFORCED`) and no longer clearable. CS-026 (2026-11-17) adds an optional pincode with a place name from a built-in list and an optional one-time "Use my location" (position mapped to the nearest pincode on the server, never stored). | CS-005, CS-025, CS-026, [PR #148](https://github.com/brollysolutions/client1/pull/148), migration `e4b5c6d7e8f9` |
| Vehicle arrangements | One dedicated arrangement per site visit; Admin enters transport details, the service automatically assigns an eligible real-estate or dual-line Employee, the assignee fulfils it, and the owning Client follows it read-only. | CS-006, [PR #149](https://github.com/brollysolutions/client1/pull/149), migration `b8c9d0e1f2a3`, migration `dd45ee67ff89`, vehicle-arrangement and Employee-auto-assignment tests |
| Authenticated personalization | Client/Agent dashboard banner layers and Client offers use a closed consented rule grammar; coarse optional location is retained for at most 30 days; public responses exclude targeted content. CS-026 (2026-11-17) adds pincode and city targets and matches a consenting Client's profile pincode first. | CS-008, CS-026, [PR #152](https://github.com/brollysolutions/client1/pull/152), migration `c9d0e1f2a3b4`, personalization API/RLS/web tests |

## 4. Genuine open decisions and implementation gaps

These items are not resolved merely because related scaffolding exists. They
need a separate product decision and implementation task.

### OI-004 — analytics caching

No product decision is needed until measurement shows a performance problem.
Keep direct indexed queries and defer caching to load-test evidence.

## 5. Legacy documentation references in code

Some implementation comments refer to legacy local design notes under
`docs/specs/` or `docs/ai/`, including `docs/ai/feature-status.md`. Those
original documents are not present and must not be treated as available
authority. A new derived living ledger now exists at
[`feature-status.md`](feature-status.md); it was independently reconstructed
from checked-in evidence and is not a transcription of the unseen legacy file.

Use this mapping when encountering those references:

| Legacy reference | Current source of truth |
| --- | --- |
| `docs/specs/dual-line-clients.md` | CS-001, current auth code, registration tests, and RLS migrations |
| `docs/ai/feature-status.md` | [`feature-status.md`](feature-status.md), current code/tests, and Sections 3–4 of this register |
| Feature-specific `docs/specs/*.md` | Relevant SRS/feature-list requirement, current route/service/model/migration/tests, and `SECURITY.md` |
| `docs/ai/plans/*` | Historical implementation provenance only; never product authority |

Future changes should cite checked-in documents or concrete requirement IDs.
Do not recreate missing design notes from code comments or assume their unseen
contents.

## 6. Change rules

- Do not rewrite the supplied originals to make them look current; amend the
  index and this derived register.
- Do not change accepted current behavior from a stale advisory passage alone.
- A change to CS-001 or CS-003 requires an authorization/RLS and migration review.
- Uploads, authentication, PII/KYC, payouts, and business-line scope require the
  repository security-review workflow before shipping.
- When an open item is decided, record the decision here with date, evidence,
  rollout implications, and any superseded requirement text.
