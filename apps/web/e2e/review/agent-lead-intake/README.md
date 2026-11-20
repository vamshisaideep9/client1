# Agent lead intake review evidence

Synthetic fixtures only. These screenshots were captured from the Node 22 Alpine
production standalone server for runtime candidate `2010d74a`, using
`e2e/agent-lead-intake.spec.ts` and the embedded commission case in
`e2e/admin-financial-products.spec.ts`. They contain no customer data. Screenshots are
review evidence, rather than pixel baselines or proof of a live API integration.

| View | Width | Evidence |
| --- | --- | --- |
| Loans Agent: contact and selected product | 390px | [Form](agent-loan-form-390.png) |
| Real Estate Agent: subtype with optional listing | 768px | [Form](agent-property-form-768.png) |
| Bulk results with invalid and repeated rows | 320px | [Results](bulk-results-320.png) |
| Admin: immediate rate entry without a checker | 1440px | [Rates](admin-rates-1440.png) |
| Sub Admin: proposal awaiting review | 390px | [Rates](subadmin-rates-390.png) |
| Product workspace: saved commission after an error and retry | 390px | [Commission](product-agent-commission-390.png) |

Fresh terminal verification:

- `pnpm lint`, `pnpm typecheck` and `pnpm test`: exit 0; 153 files / 1,113 tests.
- `pnpm build` in Node 22 Alpine: exit 0, all 118 pages generated. All eight
  production font hashes match the prior verified artifact.
- The unpublished restack onto final API `e70b18c3` preserves all runtime files
  from verified candidate `2010d74a`. The final API and contracts are inherited
  byte-for-byte. Fresh post-restack changed-test ESLint and typecheck exit 0.
- Final combined standalone-production Playwright run: **11 passed**, exit 0,
  3.1 minutes, covering the ten intake cases and the embedded commission case.
  API responses are explicitly mocked. The embedded case preserves rate/note
  after a failed save, retries successfully and sends no product PATCH.
- An earlier combined attempt passed ten cases but timed out awaiting the email
  detail page's full `load` event, with the expected form already rendered.
  Its unchanged traced rerun passed. The test now waits for DOM readiness,
  fills/saves the form and asserts the exact email-only PATCH; all eleven then
  pass together. No application code changed for that readiness adjustment.
- New and neighboring journeys have 36 distinct passing scenarios across
  segmented runs. This is not a final combined 36-test pass.
- Hosted CI: the upstream PR has no check runs. Mirror verify, secret-scan and
  dependency-audit jobs are blocked before startup by account billing/spending
  restrictions; all three annotations were checked and verify ran zero steps.
  GitGuardian is neutral. These are not passing hosted checks.

The design review retains the existing dashboard colors, fonts, spacing and
Radix controls. Mobile results remain readable without horizontal scrolling.
No additional motion or dependency was introduced. Security review covers
hidden-note ownership on email-only edits, formula-safe CSV results, bounded
spreadsheet parsing and generated contract consumers. The API remains the
authorization boundary; database-backed behavior is verified in the parent API
slice.
