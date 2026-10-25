# Milestone 1 verification

## Signup and saved KNN — 25 October 2026

- Application suite: **42 tests passed**, including signup, password mismatch/duplicate rejection, private workspace creation, automatic login and CSRF protection.
- Service and saved-model suites: **5 tests passed**, including saved inference without fitting, unit rescaling and short-history rejection.
- Public FreshRetailNet training sample: 400 selected store/product series; 1,065 training windows, 308 validation windows and 272 held-out test windows. KNN selected k=15. Held-out MAE 0.4439 versus previous-week baseline 0.5031; WAPE 35.77%, all in source-normalized sales units. These figures do not establish accuracy on the local demo business.
- Saved model sample executed successfully; local KNN batch updated all nine demo products with zero skips.
- The signup browser preview could not be completed: automatic browser approval review hit the account usage limit. Form rendering/behavior is covered by Django tests, but visual QA for the new signup page remains pending.

## Milestone 2 verification — 25 October 2026

The Week 3–4 implementation was exercised with 567 deterministic synthetic daily records across nine local demo products. The records are marked `demo`, and the interface explicitly states that forecast accuracy is not yet validated on real business data. A batch run generated nine product snapshots and seven category/unit snapshots. The FastAPI health route returned OK; its protected scoring route rejected a missing service token and accepted the matching token. A Django batch run also succeeded through the configured FastAPI service. The Waste intelligence page was inspected in both Marketplace and official themes with the populated demo data. CSV rollback, duplicate replacement, tenant scope, complete category-day grouping, missing history, capacity limits and risk behavior are covered by the inventory test suite.

The standalone service and optional model dependency bundle are separate from `requirements.txt`; a basic local install can run the seasonal forecast in-process. A live Redis/Celery deployment and production data calibration remain outside this local verification.

| Check | Result |
|---|---|
| `python manage.py test inventory` | **39 tests passed** |
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `node --check static/app.js` | JavaScript syntax passed |
| PowerShell parser check of `start.ps1` | No parse errors |
| `git diff --check` | No whitespace errors |
| `python -m unittest prediction_service.test_app` | **3 tests passed**: token protection, per-item batch failures, immediate scoring and capacity limits |
| Explicit LSTM fit on 63 synthetic days | Successful seven-day forecast |
| `manage.py run_predictions --business-id 1 --model lstm` | Nine product forecasts updated, zero skipped |
| Optional Prophet fit | Verification stalled locally and was stopped; not certified as working in this Windows environment |
| `python -m pip check` | No broken requirements |

Verified locally on **14 October 2026** using Python 3.12.14, Django 5.2.18, Django REST Framework 3.17.2 and SQLite.

## Automated checks

| Check | Result |
|---|---|
| `python manage.py test inventory` | **29 tests passed** |
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | No model changes missing migrations |
| `python manage.py migrate` | All migrations applied, including taxonomy |
| `python manage.py collectstatic --noinput` | Static assets collected successfully |
| `python -m pip check` | No broken requirements |
| `node --check static/app.js` | JavaScript syntax passed |
| PowerShell parser check of `start.ps1` | No parse errors |
| `python manage.py check_expiry` | Active alerts refreshed successfully |
| `start.ps1 -Port 8002` | Launcher applied migrations, started Django and its hidden expiry watcher |
| Background watcher log | Five successive scheduled checks completed with five active alerts and no error output |

The suite covers inventory CRUD and audit preservation; cross-business list/detail/mutation isolation; foreign product/batch rejection; authentication and CSRF; dates, quantities, duplicate records and precision; expiry boundaries and overrides; alert acknowledgement/resolution/reopening; CSV success, malformed files, limits and full rollback; POS token authentication and retry references; stale-edit conflicts; donation stock deductions and history; the periodic watcher and Celery task logic.

Only the test class uses a fast password hasher; the running app retains Django's normal password hashing.

## Browser checks

Using the local Codex browser, the following were exercised against the running server:

- Signed in with the generated demo account and loaded real database-backed counts and inventory rows.
- Created a new sample product and batch through the nested dashboard forms.
- Looked up that product by its exact barcode/QR value.
- Adjusted stock from 15.500 kg to 15.000 kg and confirmed the matching history entry and reason.
- Uploaded `examples/demo-tomatoes-qr.png` through the scanner image chooser; the image decoded to `8901000000011` and displayed the seeded tomato batch.
- Checked the dashboard at a 390 × 844 phone viewport, corrected page-level horizontal overflow, and confirmed workspace settings and sign-out remain accessible. The inventory table and navigation scroll within their own regions.
- Inspected and saved the [desktop dashboard](screenshots/dashboard.png) and [mobile layout](screenshots/mobile.png).

Browser-created sample records remain in the local demo database. The database is ignored by Git; a fresh `seed_demo` run on another machine creates the original eight sample batches.

## Not verified in this environment

Physical phone-camera capture and camera permissions require a target device and HTTPS. Image decoding and the typed-code path were verified. A live Redis broker, Celery worker and Beat were not provisioned; their task logic is tested and the local watcher provides the default automatic checks. Commercial POS vendor connectivity cannot be verified without a specified vendor; its authenticated API contract is tested. Cloud deployment and load testing belong to subsequent integration work.

## FoodBridge interface redesign

The dashboard was redesigned around the document's FoodBridge identity and category-chart direction. Live stock-condition and product-category charts replace the earlier decorative overview panel. The stock register, forms, alert actions and existing API workflows remain connected to the same database.

Verified desktop sidebar collapse into an icon rail, expansion, remembered preference after reload, and navigation while collapsed. Verified the 390 × 844 mobile drawer, Escape dismissal, keyboard focus wrapping, automatic closing after selecting a destination, and absence of page-level horizontal overflow. The refreshed dashboard produced no JavaScript console errors. All 29 existing tests passed after the branding/template change.

Updated previews: [dashboard](screenshots/dashboard.png), [mobile dashboard](screenshots/mobile.png), and [mobile navigation drawer](screenshots/mobile-menu.png).

## Professional interface polish — 14 October 2026

- Self-hosted variable Plus Jakarta Sans typography, with the SIL Open Font License retained in `static/fonts/OFL.txt`.
- Emerald interface palette, consistent SVG line icons, clearer headings, independent summary cards, refined charts, status badges, tables, inputs, dialogs and login styling.
- Verified dashboard at desktop and 390px mobile widths. Mobile document width remains within the viewport.
- Verified desktop sidebar collapse persists after reload, expansion works, and mobile navigation opens, changes pages and closes correctly.
- Verified Add inventory dialog renders correctly. No browser console errors observed.
- Existing inventory suite: 29 tests passed. JavaScript syntax check passed.
- Updated desktop and mobile screenshots in `docs/screenshots/`.

## Food Rescue Marketplace palette — 14 October 2026

- Applied a deep navy, teal and warm orange theme across the dashboard, tables, alert views, forms and sign-in screen, using the supplied Surplus dashboard image as visual direction. Existing inventory data, API behavior and the FoodBridge name remain the same.
- Verified desktop overview, inventory register, alerts and batch form; checked the 390px phone layout without document-level horizontal overflow. Desktop collapse/expand and mobile navigation remain functional.
- Saved refreshed `dashboard.png`, `mobile.png`, `mobile-menu.png` and `login.png` previews. The 29 inventory tests passed; JavaScript syntax and Django system checks passed. No browser console errors were observed.

## User-selectable appearance — 14 October 2026

- Added a theme button beside the signed-in profile and on the sign-in screen. It switches between the Food Rescue Marketplace palette and the earlier white official interface, with a clear accessible label for the next action.
- The selection is saved in browser storage, restored on reload and shared with other open tabs of the same site. The dark marketplace palette remains the default for a new browser.
- Browser-verified both themes on the dashboard and sign-in screen, including live cross-tab switching and persistence after reload. Saved `dashboard-light.png` alongside the dark `dashboard.png` preview.
