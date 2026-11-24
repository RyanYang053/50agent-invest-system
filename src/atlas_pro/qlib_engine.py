"""Actual Qlib 0.9.7 in-memory data handler, dataset and linear model execution.

The caller supplies already purged folds. Test labels never enter this module.
No Qlib download, serialization, recorder, or generated code.
"""
from __future__ import annotations
import math,sys
from contextlib import redirect_stdout
from .ledger import digest,iso
from .research import num

ENGINE_VERSION="0.9.7"

def fit_predict(train_rows,test_rows,feature_names):
    import numpy as np
    import pandas as pd
    # Optional upstream modules may print import warnings. Keep JSON stdout clean.
    with redirect_stdout(sys.stderr):
        import qlib
        from qlib.data.dataset import DatasetH
        from qlib.data.dataset.handler import DataHandlerLP
        from qlib.contrib.model.linear import LinearModel
    if qlib.__version__!=ENGINE_VERSION:raise ValueError("unreviewed Qlib version")
    if not train_rows or not test_rows:raise ValueError("empty Qlib fold")
    def key(r):return (pd.Timestamp(iso(r["signal_at"])).tz_convert(None),r["security_id"])
    train_index=[key(r) for r in train_rows];test_index=[key(r) for r in test_rows]
    if len(set(train_index+test_index))!=len(train_index)+len(test_index):raise ValueError("duplicate Qlib index")
    test_start=min(x[0] for x in test_index)
    if max(x[0] for x in train_index)>=test_start or any(pd.Timestamp(iso(r["label_available_at"])).tz_convert(None)>=test_start for r in train_rows):raise ValueError("Qlib training leakage")
    if any(set(r)!={"id","security_id","signal_at","features"} for r in test_rows):raise ValueError("test labels must not enter Qlib worker")
    if any(set(r["features"])!=set(feature_names) for r in train_rows+test_rows):raise ValueError("Qlib feature drift")
    x_train=np.array([[num(r["features"][k]) for k in feature_names] for r in train_rows])
    y_train=np.array([num(r["label"]) for r in train_rows])
    x_test=np.array([[num(r["features"][k]) for k in feature_names] for r in test_rows])
    # Fit scaling on training features only, as Atlas's Ridge baseline does.
    from sklearn.preprocessing import StandardScaler
    scaler=StandardScaler().fit(x_train)
    train_x=scaler.transform(x_train);test_x=scaler.transform(x_test)
    values=np.column_stack([np.concatenate([train_x,test_x]),np.concatenate([y_train,np.full(len(test_rows),np.nan)])])
    index=pd.MultiIndex.from_tuples(train_index+test_index,names=["datetime","instrument"])
    columns=pd.MultiIndex.from_tuples([("feature",k) for k in feature_names]+[("label","LABEL0")])
    frame=pd.DataFrame(values,index=index,columns=columns).sort_index()
    with redirect_stdout(sys.stderr):
        handler=DataHandlerLP.from_df(frame)
        ds=DatasetH(handler=handler,segments={"train":(min(x[0] for x in train_index),max(x[0] for x in train_index)),"test":(test_start,max(x[0] for x in test_index))})
        # Verify exact membership before training; absent purged dates never enter handler.
        actual=ds.prepare("train",col_set=["feature","label"],data_key=DataHandlerLP.DK_L)
        features=ds.prepare("test",col_set="feature",data_key=DataHandlerLP.DK_I)
        if set(actual.index)!=set(train_index) or set(features.index)!=set(test_index):raise ValueError("Qlib split drift")
        if not ds.prepare("test",col_set="label",data_key=DataHandlerLP.DK_I).isna().all().all():raise ValueError("Qlib label leakage")
        model=LinearModel(estimator="ridge",alpha=1.0,fit_intercept=True,include_valid=False)
        model.fit(ds)
        predicted=model.predict(ds)
    if set(predicted.index)!=set(test_index) or len(predicted)!=len(test_index):raise ValueError("Qlib prediction identity drift")
    preds=[num(predicted.loc[k]) for k in test_index]
    # Compare the same ridge objective against a separate linear-algebra solution.
    # Qlib itself wraps sklearn Ridge; agreement is implementation verification,
    # not independent economic or algorithmic evidence.
    xc=train_x-train_x.mean(axis=0);yc=y_train-y_train.mean()
    coef=np.linalg.solve(xc.T@xc+np.eye(xc.shape[1]),xc.T@yc)
    reference=(test_x-train_x.mean(axis=0))@coef+y_train.mean()
    error=max(abs(a-num(b)) for a,b in zip(preds,reference))
    scale=max(1.0,max(abs(num(b)) for b in reference))
    if not math.isfinite(error) or error>1e-7*scale:raise ValueError("Qlib numerical disagreement")
    return preds,{"engine":"qlib","version":qlib.__version__,"model":"LinearModel.ridge","data_handler":"DataHandlerLP","dataset":"DatasetH","train_count":len(train_rows),"test_count":len(test_rows),"train_ids_sha256":digest([r["id"] for r in train_rows]),"test_ids_sha256":digest([r["id"] for r in test_rows]),"test_labels_supplied":False,"max_reference_error":error,"parameter_hash":digest({"coef":np.asarray(model.coef_).tolist(),"intercept":num(model.intercept_),"mean":scaler.mean_.tolist(),"scale":scaler.scale_.tolist()}),"can_trade":False}
