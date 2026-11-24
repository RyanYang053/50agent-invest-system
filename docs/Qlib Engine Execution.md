# Qlib engine execution (developer candidate)

Atlas now has a separate optional actual Qlib training backend, rather than
only a normalized prediction importer. Upstream interfaces were verified at
Microsoft Qlib v0.9.7 (MIT):
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/model/linear.py
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/data/dataset/handler.py
- https://github.com/microsoft/qlib/blob/v0.9.7/qlib/data/dataset/__init__.py
- https://pypi.org/project/pyqlib/0.9.7/

The existing Atlas purged cross-sectional walk-forward splitter remains the
authority. Qlib receives only eligible training rows and test features, with
no test labels. Training-only feature scaling is applied. DataHandlerLP,
DatasetH and LinearModel.ridge execute in memory; the exact row membership
is checked before training, and predictions are joined by datetime and
instrument. Each fold records Qlib version, training/test ID hashes,
parameter hash and maximum discrepancy against an independent matrix ridge
solution. The same ridge objective is used as the existing sklearn baseline;
Qlib itself wraps sklearn Ridge, so agreement is an implementation check,
not evidence of a better strategy.

Build and execute are distinct:
```bash
docker build -f sandbox/Dockerfile.qlib -t atlas-qlib:local .
image=$(docker image inspect --format '{{.Id}}' atlas-qlib:local)
bash sandbox/run-research.sh --qlib "$image" /private/qlib-demo.json
```

For a private rights-cleared real panel, pass its path and exact SHA-256:
```bash
bash sandbox/run-research.sh --qlib "$image" /private/qlib-real.json /private/panel.json FILE_SHA256
```

The fixed sandbox runs nonroot, no network, no capabilities, read-only root,
no mounted home/repository, no broker/provider credentials, resource limits
and an immutable local image ID. No arbitrary Qlib scripts, dataset downloads,
pickle deserialization, model artifact persistence, external recorder or
broker route. Real data must be separately licensed, versioned and
independently qualified. The image pins top-level dependencies but does not
constitute a fully hashed transitive build.

CI requires actual Qlib calls in an isolated container on a deterministic
synthetic panel and checks fold receipts and numerical agreement. The
existing sklearn-only job remains intact. CI is not professional competence,
market alpha, or independent historical holdout certification. This
candidate does not implement RD-Agent or LEAN engine execution, production
deployment, or automatically authorize changes to any investment method.
