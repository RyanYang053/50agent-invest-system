import copy
import pytest
from atlas_pro.quant_train import synthetic_panel, train_panel
from atlas_pro.ledger import iso

@pytest.fixture(scope='module')
def result():
    return train_panel(synthetic_panel(days=70))

def test_real_fit_and_provenance(result):
    assert result['status']=='SYNTHETIC_RESEARCH_ONLY'
    assert result['folds']==2 and not result['can_trade'] and not result['promotion_allowed']
    for name,m in result['models'].items():
        assert m['n_predictions']==160 and m['n_dates']==20
        assert m['mean_rank_ic']>.5
        assert m['mae']<.002
        assert len({r['id'] for r in m['predictions']})==160
        assert all(iso(r['train_max_label_available_at'])<iso(r['signal_at']) for r in m['predictions'])

def test_repeatable(result):
    assert result==train_panel(synthetic_panel(days=70))

def test_reject_no_training_rights():
    p=synthetic_panel();p['synthetic']=False
    with pytest.raises(PermissionError): train_panel(p)

@pytest.mark.parametrize('change', ['duplicate','future','bad_feature','bad_label','missing_evidence','schema','chronology','same_asset','no_folds'])
def test_refuse_invalid_panel(change):
    p=synthetic_panel(days=70);r=p['rows'][0]
    if change=='duplicate':p['rows'][1]['id']=r['id']
    elif change=='future':r['feature_available_at']='2030-01-01T00:00:00+00:00'
    elif change=='bad_feature':r['features']['momentum']=float('inf')
    elif change=='bad_label':r['label']=-2
    elif change=='missing_evidence':r['label_evidence_ids']=[]
    elif change=='schema':r['features']['unexpected']=1
    elif change=='chronology':p['rows'].reverse()
    elif change=='same_asset':p['rows'][1]['security_id']=r['security_id']
    else:p=synthetic_panel(days=10)
    with pytest.raises(ValueError):train_panel(p)

def test_test_labels_do_not_change_first_fold_predictions(result):
    p=synthetic_panel(days=70)
    for r in p['rows']:
        if 50<=int(r['id'].split('-')[1])<60:r['label']+=.03
    changed=train_panel(p)
    for name in result['models']:
        a=result['models'][name]['predictions'][:80];b=changed['models'][name]['predictions'][:80]
        assert [r['prediction'] for r in a]==[r['prediction'] for r in b]


def test_delayed_label_cannot_leak():
    p=synthetic_panel(days=70)
    for r in p['rows']:
        if int(r['id'].split('-')[1])<40:r['label_available_at']='2030-01-01T00:00:00+00:00'
    with pytest.raises(ValueError,match='no qualifying folds'):train_panel(p)


def test_label_time_cannot_precede_end():
    p=synthetic_panel();p['rows'][0]['label_available_at']=p['rows'][0]['signal_at']
    with pytest.raises(ValueError,match='label available before'):train_panel(p)
