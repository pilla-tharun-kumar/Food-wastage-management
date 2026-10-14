# Milestone 1 API reference

Base URL: `http://127.0.0.1:8000/api/`. All APIs require an authenticated user with a Membership. Browser sessions use Django session cookies and CSRF headers. POS integrations use a token tied to a business member:

```powershell
.\.venv\Scripts\python.exe manage.py drf_create_token kitchen
```

Send `Authorization: Token YOUR_TOKEN` over HTTPS outside localhost. Treat the token like a password. Never put it in a URL or frontend source. Use `drf_create_token -r kitchen` to rotate it. The user's business is always derived server-side; sending a business ID does not change tenancy.

## Routes

| Method | Route | Purpose |
|---|---|---|
| GET, POST | `/api/products/` | List or create tenant products |
| GET | `/api/products/{id}/` | Product details |
| GET | `/api/categories/` | Shared food taxonomy; not writable through API |
| GET, POST | `/api/inventory/` | List or create inventory batches |
| GET, PUT, PATCH, DELETE | `/api/inventory/{id}/` | Read, update, or delete a batch |
| POST | `/api/inventory/{id}/adjust/` | Signed quantity adjustment; optional idempotency reference |
| GET | `/api/inventory/expiring/` | In-stock, unexpired batches within their effective threshold |
| POST | `/api/inventory/import-csv/` | Multipart `file`; atomic CSV import |
| GET | `/api/inventory/csv-template/` | Download template with current sample dates |
| GET | `/api/summary/` | Business inventory counts and unread alert count |
| GET, PATCH | `/api/business/` | Read business; update default `expiry_alert_days` |
| GET | `/api/alerts/` | Active expiry alerts |
| GET | `/api/alerts/{id}/` | One active alert |
| POST | `/api/alerts/{id}/acknowledge/` | Mark as read |
| GET | `/api/transactions/` | Immutable stock history |
| GET | `/api/transactions/{id}/` | One transaction |
| GET, POST | `/api/donations/` | Read logs or record completed donation and reduce stock |
| GET | `/api/donations/{id}/` | One donation log |

Paginated responses contain `count`, `next`, `previous`, `results` (25 per page). Categories return a plain array. Business/summary are single objects. The authenticated browsable API is available at `/api/`.

## Create product and batch

POST `/api/products/`:

```json
{"name":"Fresh tomatoes","sku":"TOM-100","barcode":"8901234567890","category":10,"unit":"kg"}
```

Get the actual category ID from `/api/categories/`; do not assume example ID `10` exists for vegetables. `sku` and nonblank `barcode` are unique per business. Product metadata is fixed after creation in the milestone API; create another SKU for a different product definition.

POST `/api/inventory/`:

```json
{"product":1,"batch_number":"TOM-100-A","quantity":"12.500","received_date":"2026-10-14","expiry_date":"2026-10-19","storage_location":"Produce shelf","alert_days":3,"notes":"Morning delivery"}
```

Use the product ID returned by the creation call. Batch response includes product metadata, `status`, `days_to_expiry`, `effective_alert_days` and `version`. `alert_days: null` uses the business threshold. Stock quantities cannot be negative or exceed `999999999.999`. Expiry can be in the past for recordkeeping, but cannot precede receipt.

## Update without overwriting another member's change

GET the batch first, then send its `version` with PUT/PATCH:

```json
{"quantity":"10.000","storage_location":"Chiller B","version":1}
```

A successful update increments version. A stale version returns **409**; reload the batch before editing again. PATCH validates the merged received/expiry dates. A batch cannot be reassigned to a different product. DELETE also requires a JSON body: `{"version":2}`. Its audit record and related donation snapshots remain available after deletion.

## POS integration

Use an API token to create products/batches for deliveries and post signed adjustments for sales/returns:

```http
POST /api/inventory/1/adjust/
Authorization: Token YOUR_TOKEN
Content-Type: application/json

{"delta":"-2.500","reason":"POS sale","reference":"store-a-sale-482-line-1"}
```

First success: **201**, `replayed:false`. Repeating the same reference, batch, delta and reason returns **200**, `replayed:true`, with the original transaction and no second deduction. Reusing a reference for different contents returns **409**. References are unique per business. An adjustment cannot overdraw stock. Re-read and retry on a concurrent-update conflict. A create/import request is not automatically idempotent; duplicate batches are rejected.

This is the vendor-neutral integration contract. No access to a specific POS vendor was supplied; the vendor adapter must call these routes with mapped product and batch IDs. Scan lookup: `/api/products/?barcode=8901234567890` and `/api/inventory/?barcode=8901234567890`.

## Filtering

`/api/inventory/?search=tomato&category=vegetables&status=expiring&page=1`

- `search`: product name, SKU or batch number.
- `category`: food taxonomy code.
- `status`: `fresh`, `expiring`, `expired`, `out_of_stock`.
- `barcode`: exact product barcode/QR value; preserves leading zeros.
- `expiring/?days=3`: override the query window with 0–365 days; excludes expired and zero stock. Without `days`, use per-batch/business thresholds.

## Donations

POST `/api/donations/` with `{"batch":1,"quantity":"2.000","recipient":"Local community kitchen","notes":"Completed handover"}`. This atomically subtracts stock, writes a `donated` transaction and stores a donation snapshot. It rejects expired batches, nonpositive quantities and quantities greater than stock. These are records of completed donations, not marketplace listings or reservations. Donation POST does not support automatic retry deduplication; verify the response/log before resubmitting after an uncertain network outcome.

## Errors and scope

- **400**: validation error, malformed CSV, duplicate record or invalid stock operation. CSV errors identify the offending row; no import rows are retained.
- **401**: missing/invalid authentication.
- **403**: authenticated account without business membership, or a missing CSRF token for a session-authenticated mutation.
- **404**: missing object or another business's object.
- **409**: stale batch version or conflicting POS reference.
- **429**: development API rate limit exceeded (600 requests per minute per user).

Transactions, alerts and donation logs cannot be arbitrarily edited/deleted through the API. Taxonomy is shared; products and all operational records are tenant-scoped. Django admin is reserved for trusted project administrators; stock edits are performed through the audited API.
