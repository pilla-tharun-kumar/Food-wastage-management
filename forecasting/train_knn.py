"""Reproducible public-data download, chronological evaluation and saved KNN training."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlretrieve

from .knn import MODEL_DIR, MODEL_PATH, features

REVISION = '08c1fab7f9257bc73679d415d65d644165d351d4'
SOURCE = 'https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K'
URL = f'{SOURCE}/resolve/{REVISION}/data/train.parquet'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--series', type=int, default=400)
    parser.add_argument('--data', type=Path, default=Path('data/raw/freshretail_train.parquet'))
    args = parser.parse_args()
    if args.series < 10:
        parser.error('Use at least 10 product/store series.')
    import joblib
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.metrics import mean_absolute_error

    args.data.parent.mkdir(parents=True, exist_ok=True)
    if not args.data.exists():
        temporary = args.data.with_suffix('.download')
        print('Downloading pinned public FreshRetailNet data...', flush=True)
        urlretrieve(URL, temporary)
        temporary.replace(args.data)
    columns = ['store_id', 'product_id', 'dt', 'sale_amount', 'stock_hour6_22_cnt', 'first_category_id']
    parts, selected = [], None
    for batch in pq.ParquetFile(args.data).iter_batches(batch_size=65536, columns=columns):
        frame = batch.to_pandas()
        keys = list(zip(frame.store_id, frame.product_id))
        if selected is None:
            selected = set(list(dict.fromkeys(keys))[:args.series])
        parts.append(frame.loc[[key in selected for key in keys]])
    frame = pd.concat(parts, ignore_index=True)
    frame['dt'] = pd.to_datetime(frame.dt)
    if frame.duplicated(['store_id', 'product_id', 'dt']).any():
        raise ValueError('Duplicate product/store dates in source.')
    dates = sorted(frame.dt.unique())
    train_end, validation_end = pd.Timestamp(dates[int(len(dates)*.70)-1]), pd.Timestamp(dates[int(len(dates)*.85)-1])
    splits = {name: [] for name in ('train', 'validation', 'test')}
    for (store, product), group in frame.groupby(['store_id', 'product_id']):
        group = group.sort_values('dt')
        values = group.sale_amount.to_numpy(dtype=float)
        for index in range(28, len(group)-6):
            window = group.iloc[index-28:index+7]
            if len(window.dt.diff().dropna().unique()) != 1 or window.dt.diff().dropna().iloc[0] != pd.Timedelta(days=1):
                continue
            if not np.isfinite(values[index-28:index+7]).all() or (values[index-28:index+7] < 0).any():
                continue
            if group.iloc[index:index+7].stock_hour6_22_cnt.gt(0).any():
                continue  # Censored targets are not treated as known full demand.
            start, end = group.dt.iloc[index], group.dt.iloc[index+6]
            split = 'train' if end <= train_end else 'validation' if start > train_end and end <= validation_end else 'test' if start > validation_end else None
            if split:
                history = values[index-28:index]
                vector, scale = features(history, start.weekday())
                splits[split].append((vector, values[index:index+7]/scale, scale, history,
                                      start, int(store), int(product)))
    if any(len(items) < 35 for items in splits.values()):
        raise ValueError('Insufficient uncensored windows; increase --series.')
    def arrays(name):
        rows = splits[name]
        return np.array([row[0] for row in rows]), np.array([row[1] for row in rows]), np.array([row[2] for row in rows])[:,None]
    xtrain, ytrain, _ = arrays('train')
    xval, yval, sval = arrays('validation')
    xtest, ytest, stest = arrays('test')
    candidates = []
    for k in (3, 7, 15):
        model = make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k, weights='distance', n_jobs=1))
        model.fit(xtrain, ytrain)
        error = mean_absolute_error(yval*sval, model.predict(xval)*sval)
        candidates.append((error, k, model))
    validation_mae, k, model = min(candidates, key=lambda item:item[0])
    predicted = model.predict(xtest)*stest
    actual = ytest*stest
    baseline = np.array([row[3][-7:] for row in splits['test']])
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH, compress=3)
    report = {'source': SOURCE, 'revision': REVISION, 'license': 'CC-BY-4.0',
              'attribution': 'Dingdong-Inc, FreshRetailNet-50K, Wang et al. (2025), arXiv:2505.16319',
              'source_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'model': 'KNeighborsRegressor', 'neighbors': k, 'series': len(selected),
              'windows': {key:len(value) for key,value in splits.items()},
              'train_end': str(train_end.date()), 'validation_end': str(validation_end.date()),
              'validation_mae': float(validation_mae), 'test_mae': float(mean_absolute_error(actual,predicted)),
              'seasonal_test_mae': float(mean_absolute_error(actual,baseline)),
              'test_wape': float(np.abs(actual-predicted).sum()/max(actual.sum(),.001)),
              'units': 'Source-normalized sales; local inference rescales relative patterns using the last 28-day mean.',
              'limitations': 'Historical sample, not a live feed. No purchase/waste labels. Targets with stockouts excluded. Transfer to local product units requires validation.'}
    (MODEL_DIR/'demand_knn_metrics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sample = splits['test'][0]
    samples = Path('examples'); samples.mkdir(exist_ok=True)
    payload = {'model':'knn','history':[{'date':str((sample[4]-pd.Timedelta(days=28-i)).date()),
               'sales':float(value),'purchases':0,'waste':0} for i,value in enumerate(sample[3])],
               'stock':float(sample[3].mean()*10),'days_to_expiry':3,
               'storage_capacity':float(sample[3].mean()*20),'lead_days':3}
    (samples/'knn_sample.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    (samples/'knn_sample_expected.json').write_text(json.dumps({'actual_next_7_days':list(map(float,sample[1]*sample[2])),
        'note':'Held-out real sales; stock/capacity are illustrative, purchases/waste are placeholders and not model features.'},indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__ == '__main__':
    main()
