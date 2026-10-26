# Milestone 2 — Weeks 3–4 walkthrough

The project brief calls for historical sales/purchase/waste preparation, daily and weekly demand forecasting, waste-risk flags, smart reorder suggestions, a FastAPI microservice and scheduled/on-demand prediction. This implementation covers those workflows with clearly labeled synthetic data until the team supplies real history.

| Brief requirement | Implemented behavior | Demonstration |
|---|---|---|
| Historical data | Tenant-scoped daily observations, atomic CSV import and coverage report | Import the template, then inspect `/api/demand/coverage/` |
| Product/category series | Continuous product days and complete category/unit days; missing dates never become zero | Open `/api/demand/category-series/?category=vegetables&unit=kg` |
| Demand forecast | Seven daily predictions and a weekly sum; seasonal baseline, optional Prophet/LSTM; holdout MAE for model selection | Open Smart intelligence and inspect the model label and mini chart |
| Waste risk | 0–100 score using stock, nearest expiry, surplus against forecast demand, with high/medium/low bands | Compare expiring stocked products in the product outlook table |
| Smart reorder | Demand over supplier lead plus safety days, limited by remaining storage capacity; high-risk items receive no reorder suggestion | Set capacity/lead time in a product's Plan action |
| FastAPI | Private `/v1/analyze` scoring route with optional shared service token; Django retains tenancy and persistence | Start port 8100 and set `PREDICTION_SERVICE_URL` |
| Batch and on-demand | Management command, local daily watcher, Celery Beat daily schedule, and API run action | Run `manage.py run_predictions` or click Run predictions |

## Reproducible local demo

1. Install `requirements.txt`, copy `.env.example` to `.env`, migrate, then run `seed_demo` and `seed_demand_demo`. The second seed creates 63 deterministic, **synthetic** days of sales, purchases and waste and is idempotent.
2. Run `manage.py run_predictions`. The command prints updated and skipped product counts. A product needs at least 21 complete consecutive days through yesterday; incomplete series are skipped with a reason.
3. Start `start.ps1`, sign in and select **Smart intelligence**. Review the data-source banner, coverage, risk scores, seven-day demand, reorder recommendations and category outlook. Toggle between Marketplace and official themes to verify both.
4. Select **Import demand history** to download the CSV template. Import real completed days when available, then select **Run predictions**. Use **Plan** for a product to set capacity and supplier lead time.
5. Optional service demo: install `requirements-prediction.txt`, start `uvicorn prediction_service.app:app --host 127.0.0.1 --port 8100`, set Django's `PREDICTION_SERVICE_URL` to `http://127.0.0.1:8100`, and restart Django. Use the same `PREDICTION_SERVICE_TOKEN` in both processes if enabling the service token.

## Status and limitations

The Smart intelligence model selector offers saved KNN, Seasonal, LSTM and Compare models. Select LSTM and click Run predictions to demonstrate the AI model without a terminal. The button shows a calculating state during training; skipped products report their reason. The dashboard selects saved KNN by default; install requirements-knn.txt. Seasonal remains available without model dependencies.

Verified locally: all nine demo products completed an explicit LSTM batch run without skips; the application suite has 39 passing tests and the service suite has three passing tests. LSTM satisfies the brief's Prophet-or-LSTM model requirement. Prophet's optional implementation did not finish local verification and should be treated as unverified. Automatic comparison considers seasonal and LSTM; scheduled runs default to seasonal for responsiveness. Use `--model lstm` for the verified AI model or `--model auto` to compare it with the baseline.

All Milestone 2 routes, persistence, scoring, UI and batch scheduling are implemented. The current local demo is based on synthetic observations; model accuracy has not been validated against actual food-business outcomes. Prophet and PyTorch LSTM require `requirements-models.txt` and sufficient history; the baseline works with the core install. Reorder output is a recommendation, not an automated purchase. Forecasts use available sales as observed demand; unmet demand during stockouts is not estimated. Multi-batch expiry is represented by the nearest in-stock expiry date, so operational review remains necessary before redistribution decisions. Production deployment still needs real data, calibration, monitoring, PostgreSQL and a privately secured service deployment.
