# Local demo data

The comprehensive demo dataset populates the implemented Admin, Sub Admin,
Client, Agent, Telecaller, and Employee workspaces with deterministic synthetic
records. It is a public development fixture, not a production bootstrap.

Run it from the repository root with the local Docker stack healthy:

```bash
docker compose exec -T api uv run python -m app.scripts.seed_demo --verify
```

The command is idempotent. It reconciles the fixed demo accounts, inserts only
missing rows from its UUID namespace, creates three synthetic media examples
through the existing local managed-upload paths, and then verifies every login
and primary role API. It refuses to run unless `ENV=development`.

Use `--credentials` to print the roster without writing data, or `--skip-media`
when intentionally running without object storage or ClamAV. A media skip is not
proof that upload-backed UI works. The development droplet writes demo media to
its dedicated DigitalOcean Space (`infra/dev-droplet/README.md`, step 4b).

## Credentials

Login: <http://localhost:3001/login>

| Workspace | Mobile | Password | Scope |
| --- | --- | --- | --- |
| Admin | `+919000001001` | `Demo@1234` | Platform |
| Admin (checker) | `+919000001002` | `Demo@1234` | Platform |
| Sub Admin | `+919000001003` | `Demo@1234` | Platform + payout-request preparation |
| Client | `+919000001004` | `Demo@1234` | Loans + Real Estate |
| Client (referred journey) | `+919000001005` | `Demo@1234` | Loans + Real Estate |
| Agent | `+919000001006` | `Demo@1234` | Loans |
| Agent | `+919000001007` | `Demo@1234` | Real Estate |
| Telecaller | `+919000001008` | `Demo@1234` | Loans |
| Telecaller | `+919000001009` | `Demo@1234` | Real Estate |
| Employee | `+919000001010` | `Demo@1234` | Loans |
| Employee | `+919000001011` | `Demo@1234` | Real Estate |

The first Admin becomes Main Admin only when the database has no existing Main
Admin. On an established local volume, the seeder preserves the existing Main
Admin and creates both demo Admins as ordinary platform Admins. This avoids
silently reassigning an unrelated account; use a deliberately fresh local
database when testing Main-Admin-only provisioning controls.

## Populated journeys

The dataset includes representative records for:

- assigned and due leads on both lines, Agent-introduced leads, Telecaller call
  activity, and converted/closed history;
- active, closed, and new loan applications, one transaction-history entry,
  and a sanitized synthetic salary-slip PDF;
- approved catalogue properties, Agent/Sub Admin submissions in pending,
  approved, and rejected states, bookmarks, enquiries, site visits, deals, and
  an assigned vehicle pickup;
- Employee document-collection, background-check, overdue, and property-visit
  tasks, including a confirmed synthetic task PDF and sanitized visit photo;
- pending/paid payouts, fee cashbacks, Agent commissions, referral rules,
  pending/paid referrals, and recipient transaction ledgers without calling a
  payment provider;
- live/pending banners, active/draft offers, published/draft content, support
  tickets, agent applications, per-role notifications, and audit examples.

Existing migration-owned Financial Product forms and configured providers are
reused. The seeder deliberately does not invent lender identities or logos,
create fake KYC references, call email/voice/push/payment providers, or weaken
authorization/RLS. Those boundaries need their real UI flows or separately
approved source material.

## Bulk test data

For volume and edge-case testing, a second, much larger dataset sits beside
the curated demo accounts:

```bash
docker compose exec -T api uv run python -m app.scripts.seed_bulk --verify
```

It is development-only, idempotent and resumable (every row has a fixed
UUIDv5 id in its own namespace and is inserted only when missing), and it
never touches the demo accounts above or any unrelated row. `--credentials`
prints the roster; `--skip-media` writes rows only. Like the demo seeder, a
rerun restores each bulk account's password and planned account status.

The bulk Telecallers and Employees are active staff, so on a shared
environment the normal round-robin also assigns new real leads and tasks to
them.

All bulk accounts use the same password as the demo accounts (`Demo@1234`) on
mobiles `+91 92000 xxxxx`:

| Accounts | Mobiles | Notes |
| --- | --- | --- |
| 2 Admins | `+919200000101`-`102` | Ordinary platform Admins; never Main Admin |
| 9 Sub Admins | `+919200000111`-`119` | 01-05 manage the five teams; 06-07 may prepare payout requests |
| 15 Telecallers | `+919200000131`-`145` | 01-08 Loans, 09-15 Real Estate; 08 suspended; 07 and 15 in no team |
| 15 Employees | `+919200000151`-`165` | 01-08 Loans, 09-15 Real Estate; 15 inactive; 08 in no team |
| 15 Agents | `+919200000171`-`185` | 01-08 Loans, 09-15 Real Estate (with RERA codes); 15 suspended |
| 195 Clients | `+919200010001`-`10195` | 001-085 Loans, 086-170 Real Estate, 171-195 both lines |
| 1,806 coverage clients | `+919200020001`-`21806` | One line each; see "Per-person coverage" below |

The teams are Loans callers A and B, Real Estate callers, Loans field team and
Real Estate field team.

What it covers:

- 110 published listings across all nine property subtypes, sale and rent,
  every RERA applicability, ready and under construction, each passing the
  same `SubmissionFacts` validation as a real submission; 3-6 gallery photos
  each and a 360 panorama on every third; 24 submissions (pending, approved,
  rejected) with photos, panoramas and a PDF.
- Leads in every status (direct, Agent-introduced, expired Agent protection,
  released, unassigned) with call activity and overdue, due and upcoming
  callbacks.
- Loan applications in all 13 statuses across the configured loan products,
  with form answers validated against each product's own form, sanction and
  fee details, transaction history, and loan documents (some verified, some
  with review notes); credit-card enquiries.
- Bookmarks, enquiries, site visits, vehicle pickups and property deals in
  every status.
- Employee tasks of every type in every status, with collected documents and
  visit photos.
- Fee cashbacks, commissions and referrals in every status, and payouts in all
  eight maker/checker and gateway states with matching ledger rows. Gateway
  ids are synthetic; no payment provider is called.
- Support tickets in every status and category, two notifications per staff
  account and per sampled client, and audit examples.
- Account states: suspended and pending-password-reset users; pending,
  suspended and inactive profiles; five profiles per line with no activity at
  all for empty-state screens.

### Per-person coverage

Every active Telecaller, Employee and Agent sees at least five records for
every value of every filter on their own screens, so any filter can be tested
from any account:

- Telecallers: each lead status, each last call outcome (and "not called"),
  each interest level, each referral source (direct, Agent, client), and, on
  Loans, each of the 13 loan statuses. 120 coverage clients per Loans
  Telecaller and 48 per Real Estate Telecaller.
- Employees: each task status and task type, the same lead filters through
  their tasks' leads, and, on Real Estate, assigned, completed and cancelled
  vehicle pickups.
- Agents: each lead status including Expired (45 introduced clients each), each
  commission status, and, on Real Estate, pending, approved and rejected
  listings.

`test_seed_bulk.py` checks these minimums from the plan, and a run against the
API confirmed them for every account.

Not included, on purpose: banners, campaign artwork and videos (use
`seed_demo` for those), and Aadhaar/PAN or other KYC images. Media is written
directly at the upload services' canonical keys, so seeding does not use up
any account's hourly upload quota.

## Reruns and local state

Rerunning is safe and refreshes the known password for the fixed demo accounts.
It does not delete unrelated data or clean a test-polluted database. The command
stops on any collision where a demo mobile, email, or deterministic UUID belongs
to another account rather than taking that identity over.

The output from `--verify` is the authoritative quick check: all eleven accounts
must report a successful login, their expected role and line, and non-empty
representative data from their primary RLS-backed APIs. A skipped or failed
verification is not a passing demo-data setup.
