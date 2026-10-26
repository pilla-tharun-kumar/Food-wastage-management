# FoodBridge architecture — Milestones 1 and 2

The first two milestones deliver inventory operations and demand/Smart intelligence. Django serves the responsive dashboard and tenant-scoped REST API. The browser uses same-origin session authentication, while POS clients use tokens. SQLite keeps local setup simple; the ORM allows a later PostgreSQL migration. An optional FastAPI process performs prediction scoring behind Django.

```mermaid
flowchart LR
    Browser[Responsive dashboard / barcode scanner] -->|Session and CSRF| API[Django REST Framework]
    POS[POS client] -->|Token authenticated REST| API
    CSV[CSV upload] --> API
    API --> Validation[Validation and tenant permissions]
    Validation --> Service[Atomic stock and donation services]
    Service --> DB[(SQLite database)]
    Watcher[Local scheduled watcher] --> Alerts[Expiry alert service]
    Celery[Optional Celery Beat / Redis worker] --> Alerts
    Service --> Alerts
    Alerts --> DB
    DB --> API
    API --> Notifications[In-app alerts and counts]
    DemandCSV[Daily sales / purchases / waste CSV] --> API
    API --> Demand[(Demand observations)]
    Demand --> Predictor[Daily batch / on-demand prediction]
    Predictor -->|Optional private HTTP| FastAPI[FastAPI scoring service]
    Predictor --> Snapshots[(Product and category prediction snapshots)]
    Snapshots --> API
```

## Database relationships

```mermaid
erDiagram
    USER ||--o| MEMBERSHIP : belongs_via
    BUSINESS ||--o{ MEMBERSHIP : includes
    BUSINESS ||--o{ PRODUCT : owns
    CATEGORY ||--o{ PRODUCT : classifies
    PRODUCT ||--o{ INVENTORY_BATCH : has
    BUSINESS ||--o{ INVENTORY_BATCH : scopes
    INVENTORY_BATCH ||--o| EXPIRY_ALERT : triggers
    INVENTORY_BATCH o|--o{ STOCK_TRANSACTION : records
    INVENTORY_BATCH o|--o{ DONATION_LOG : supplies
    BUSINESS ||--o{ STOCK_TRANSACTION : owns
    BUSINESS ||--o{ DONATION_LOG : owns
    BUSINESS ||--o{ EXPIRY_ALERT : owns
    PRODUCT ||--o{ DEMAND_OBSERVATION : records
    PRODUCT ||--o{ PREDICTION_SNAPSHOT : forecasts
    BUSINESS ||--o{ CATEGORY_PREDICTION_SNAPSHOT : forecasts
```

Each user has one business membership. Several users can share the same business. Categories are a global read-only taxonomy. Product SKU and nonempty barcode are unique within a business; batches are unique by business, product and batch number. Business IDs are assigned from the authenticated membership, never from client-selected scope. Related product/batch fields only accept objects belonging to that business.

## Stock integrity

Create, update, adjustment, delete, donation and CSV services use database transactions. Updates use a version check and conditional database write to detect concurrent changes. Stock cannot fall below zero. Transaction snapshots retain product identity, batch dates, notes, storage and units after batch deletion. Donation logs also retain a snapshot. POS transaction references deduplicate repeated adjustments.

CSV imports run in one transaction: a later invalid row rolls back earlier products, batches, alerts and history. Files are limited to 2 MB and 1,000 rows. Dates use ISO format and units allow a fixed set of values. Category codes are explicit; classification does not pretend to use an AI model.

## Expiry behavior

Dates are interpreted in the configured business deployment time zone (`Asia/Kolkata` by default). A batch threshold overrides the workspace default. The status sequence is zero stock → expired → within threshold → fresh. A persistent alert exists per batch; repeated checks update it instead of generating duplicates. Acknowledgement is separate from resolution. Expiry or severity changes and reopening risk clear acknowledgement.

The default Windows launcher runs expiry and daily prediction watchers alongside Django. Celery Beat and Redis provide an alternative scheduler. The dashboard also refreshes current alerts during reads and polls while visible. Notifications are in-app, with no external delivery provider required.

## Prediction behavior

Daily observations are scoped to the authenticated business and SKU. A product series needs consecutive completed days ending yesterday; missing dates are not treated as zero. Category histories only use dates present for every product sharing a category and stock unit. Django passes history, current stock, closest expiry and planning settings to either its in-process scoring library or the configured FastAPI service. The service does not query or store tenant data. A seven-day forecast feeds a transparent waste-risk and capacity-aware reorder rule. Snapshots store model identity, backtest error and the inputs needed to explain a result. Synthetic demo rows are explicitly labeled and should not be used to claim production accuracy.

## Implementation boundaries

- This is a local milestone application, not a deployed production service. Production hosting needs HTTPS, PostgreSQL, centralized rate limiting, backups, logging and environment-specific security settings.
- Members of a business have equal permissions; role-based owner/staff access and invitation flows are future work. Trusted Django admins can provision memberships and taxonomy.
- Inventory status filtering currently evaluates per-batch thresholds in Python for portability. Large inventories should move this calculation into database expressions and add indexes after measuring query plans.
- SQLite serializes writes. Conditional updates reject stale clients, but large concurrent workloads require a production database and load testing.
- Codes identify existing products; no third-party barcode database or commercial POS adapter is included.
- The stock ledger retains operational history; it is not a tamper-proof compliance ledger against trusted database administrators.
- NGO matching, reservations, pickup scheduling and impact estimates remain outside Weeks 1–4.

## Decision on frontend stack

The supplied brief explicitly introduces React dashboards in Weeks 5–6. The current milestones use Django templates and vanilla JavaScript to keep setup small and demonstrate the REST integration now. Later React clients can use the same tenant-scoped API rather than reimplementing inventory rules.
