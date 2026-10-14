# Milestone 1 completion and demonstration

## Source analysis

The supplied Word brief specifies five requirements for **Weeks 1–2: Inventory Management & Expiry Tracking System**. The WhatsApp notes confirm Django/DRF and internally built APIs and propose Celery/Redis. The Word brief also requires scanning, categorization, tenant storage, transaction history and donation-log storage; these are included rather than limiting delivery to basic CRUD.

## Requirement mapping

| Week 1–2 requirement | Delivered implementation | Evidence |
|---|---|---|
| Manual inventory input, CSV upload and POS REST integration | Dashboard forms; product and batch APIs; atomic CSV importer; token-authenticated stock adjustments with retry references | CRUD, CSV, rollback and POS tests; API guide |
| Expiry tracking and automated threshold alerts | Business default and batch overrides; persistent alerts; local watcher; Celery task/Beat configuration; in-app notifications | Date-boundary, acknowledgement, resolution, threshold and task tests |
| Food taxonomy with perishability and storage | Ten seeded categories with codes, risk and storage guidance; taxonomy screen and API | Category tests and migration |
| Barcode/QR scanning with mobile-friendly interface | Locally bundled camera/image scanner, exact-code lookup, typed/USB input, responsive forms and tables | Browser lookup checks; physical camera acceptance remains device-dependent |
| Multi-tenant inventory, transactions and donation logs | Business Membership scope; separate products/batches; stock audit snapshots; completed donation logs | Cross-business denial tests, immutable history and donation stock tests |

## Suggested Week 1 and Week 2 presentation split

**Week 1:** explain the requirements, show the architecture/database schema, demonstrate business setup and login, inspect the seeded taxonomy, and create inventory using manual forms and REST APIs.

**Week 2:** demonstrate CSV success and rejection, expiry filtering and scheduled checks, scanner lookup and stock adjustment, tenant isolation, transaction history and donation logging. Finish with the automated test results.

## Ten-minute demo script

1. Run migrations, `seed_demo`, and `start.ps1`. Sign in using the generated demo credentials. Clarify that these are sample inventory records.
2. Explain the dashboard's batch counts. Show expiring and expired filters; expiry-date order supports first-expiry-first-use.
3. Add a product or select an existing one; save a batch with a received date, expiry, quantity and location.
4. Edit its quantity and show Activity history. Explain the `version` field that prevents stale edits from overwriting newer changes.
5. Download the CSV template, update it, import it, then deliberately try a negative quantity. Show the row error and explain that the entire file rolls back.
6. Open Workspace settings and change the expiry window. Show active alerts and acknowledge one. The alert remains visible while the batch remains at risk.
7. Open Scan barcode / QR. Type demo barcode `8901000000011` or scan an image containing that exact value. Show the matching tomato batch and adjust its stock with a reason.
8. Log a completed donation from nonexpired stock. Show the reduced quantity, donation log and stock transaction.
9. Explain a second business's data isolation using the automated tests. Create a second account with `create_business` for a live two-login demonstration if desired.
10. Run `python manage.py test inventory` and show the green result. Show `docs/API.md` as the integration handoff.

## Acceptance checks and practical limits

- All 29 automated tests passed. They exercise inventory operations, cross-tenant access, date boundaries, stock constraints, CSV errors/rollback, POS retry behavior, alert lifecycle, donation deductions, session CSRF and task logic. See [verification results](VERIFICATION.md).
- Local browser checks cover sign-in, product/batch creation, stock adjustment, history, barcode lookup, actual QR image decoding and a phone-sized layout. A physical phone-camera scan must be checked on the mentor's target phone using HTTPS. Image/typed-code fallback avoids blocking the desktop demo.
- In-app alerts are the selected notification channel. Email/SMS was not specified; no external messages are sent.
- The local watcher is runnable without Redis. Celery/Beat configuration is supplied, but live Redis worker delivery requires starting those services and is a separate environment check.
- The POS API contract is implemented and tested. A vendor-specific adapter requires actual POS vendor details and credentials, which were not supplied.
- No AI forecast or waste-risk model is claimed in this milestone. Perishability labels are taxonomy metadata, not learned predictions.
- GitHub upload, team assignment approval and mentor sign-off are human handoff steps. This implementation does not send team messages or push commits.

## Submission contents

Submit source, migrations, requirements, `.env.example`, templates/static assets, scanner license, tests and the `docs/` folder. Include the brief only if your team's repository can share it. Exclude `.env`, `.venv`, SQLite files, credentials, logs and generated QA artifacts. README provides a clean-machine setup path.
