# Saved KNN demand model

Source: [Dingdong-Inc/FreshRetailNet-50K](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K), pinned revision `08c1fab7f9257bc73679d415d65d644165d351d4`. Attribution: Dingdong-Inc; Wang et al. (2025), *FreshRetailNet-50K*, arXiv:2505.16319. License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This is historical real-world retail data, not a live feed. Source sales are globally normalized; the data does not contain purchase or waste labels.

## Train once

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-knn.txt
.\.venv\Scripts\python.exe -m forecasting.train_knn
```

The script downloads a pinned Parquet source into ignored `data/raw/`, selects a deterministic sample of up to 400 store/product series from its first batch, and checks unique dates, continuity, finite and nonnegative sales. It excludes forecast target windows affected by stockouts. Sampling is for a practical local demonstration, not a representative benchmark of all stores or categories.

Features describe the preceding 28 days: 14 daily relative sales lags, recent weekly average, variability and forecast-start weekday. Seven output values predict the coming week. Each window is normalized by its own preceding 28-day mean, which is available at prediction time. A scaler and distance-weighted KNN are fitted only on the training split. Later calendar dates form validation and test splits; windows crossing target boundaries are excluded. The validation split selects k from 3, 7 and 15. The untouched test split reports MAE, WAPE and the previous-week baseline. The model is not assumed to outperform the baseline.

Outputs: `models/demand_knn.joblib`, `models/demand_knn_metrics.json`, and a held-out JSON sample in `examples/`. The metrics include the dataset SHA-256, pinned revision, sample/window counts and cutoff dates. The saved model contains training feature/target patterns derived from this public dataset. Keep its attribution with redistribution. Load only this locally generated artifact; never load untrusted uploaded pickle/joblib files.

## Use and test without retraining

```powershell
.\.venv\Scripts\python.exe -m forecasting.test_sample
.\.venv\Scripts\python.exe manage.py run_predictions --model knn
```

Choose **Smart intelligence → KNN · saved model → Run predictions**, or POST the sample JSON to FastAPI `/v1/analyze` with the configured service token. KNN needs 28 continuous completed history days. The model is loaded from disk and cached, rather than fitted on each request. Its relative outputs are rescaled by each local product's recent mean to retain that product's units. This transfer requires validation on actual local history before purchasing decisions.

`examples/knn_sample.json` contains real held-out sales history. Stock, capacity and expiry are illustrative inputs for testing the risk/reorder engine; purchase/waste zeros are placeholders, not real measurements or KNN features. `knn_sample_expected.json` contains the following seven actual sales values. Waste risk remains an expiry/stock/forecast calculation, not a learned waste classifier.
