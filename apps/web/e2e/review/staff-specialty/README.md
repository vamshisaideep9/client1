# Staff specialties and role identifiers

Batch 3 web uses the existing generated contract, navy/sky/white components,
fonts and private routes. No dependency, new motion or public page changed.
The API parent is [upstream #390](https://github.com/brollysolutions/client1/pull/390)
and [mirror #91](https://github.com/vamshisaideep9/client1/pull/91).

Validation on the final runtime source:

- Full web lint and typecheck pass; **1,119 Vitest tests in 154 files pass**.
- Node 22 Linux production build passes, generating **118 pages**. All eight
  emitted font hashes equal the original font bytes. The offline build logged
  existing public-catalogue timeout fallbacks; no public source changed.
- **26 Playwright journeys pass together**, exit 0, 1.6 minutes, against the
  completed production artifact at a dedicated local port. The command is
  `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3103 pnpm test:e2e staff-specialty.spec.ts profile-menu-touch.spec.ts sub-admin-teams.spec.ts --workers=1`.
  All requests use synthetic fixtures, with no live account or data changes.
- The 18 new journeys cover optional specialty provisioning, incompatible
  role/line clearing, catalogue retry/filtering, save retry/clear and directory
  refresh, a delayed-save account switch, all six role codes, absent metadata,
  both team lines, manager member detail and both task-counterpart directions.
  Eight neighboring journeys cover touch/hover account menus and team workflows.
- The first browser run passed 25/26; one test expected raw 503 detail despite
  the shared API client deliberately replacing it with a generic error. The
  corrected test asserts the exact safe message, retained input and identical
  retry request bodies. The full rerun passes; application code did not change.

Visual review applied the pinned Taste/Impeccable guidance within the approved
operational design, Kowalski's valid no-new-motion choice and the installed
Apple Design checklist. No outstanding design divergence or accessibility/
correctness finding was identified in the checked surfaces. Long team names and
codes wrap; the menu stays within 320/390/768/1440px viewports. The selector has
labels, explanatory text, loading/empty/error feedback and retry; saving is
explicit and retained input survives failure. Existing role-sensitive profile
locks remain intact. Keyboard Escape dismissal and touch/hover menu behavior
are exercised. Manual screen-reader, large-text/zoom and physical-device checks
were not run; the account-edit screenshot is desktop, not a narrow-screen review.

Selected final-run screenshots, inspected at their native dimensions:

- [320px role/team menu](role-teams-320.png)
- [390px role/team menu](role-teams-390.png)
- [768px role/team menu](role-teams-768.png)
- [1440px role/team menu](role-teams-1440.png)
- [390px provisioning error with retained specialty](specialty-create-390.png)
- [1440px saved account specialty](specialty-account-1440.png)
- [390px Employee task counterpart](employee-counterpart-390.png)

Security/code review retains server authorization, generated types and actual
assigned codes. It introduces no counterpart contact details, directory grant,
new dependency or client-side authorization boundary. Browser fixtures verify
presentation; the parent's PostgreSQL/RLS tests verify authorization separately.
Hosted dependency-audit findings in the unchanged Python lock remain a separate
failed gate; this evidence does not claim green hosted CI or authorize a merge.
