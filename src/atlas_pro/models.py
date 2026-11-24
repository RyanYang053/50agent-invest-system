"""Evidence-based model certification and race-safe spending reservations.

No inference network code. This gateway produces approvals for a separate client.
"""
from __future__ import annotations
from contextlib import contextmanager
import sqlite3, json, math
from decimal import Decimal
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from .ledger import digest, iso

class ModelGateway:
    def __init__(self, path, registry, roles, *, daily_limit_usd='5',monthly_limit_usd='100', local_cost_input_usd_per_m=None, local_cost_output_usd_per_m=None):
        self.path=str(path)
        self.registry=registry
        self.roles={r['agent_id']:r for r in roles}
        self.daily_limit=Decimal(str(daily_limit_usd))
        self.monthly_limit=Decimal(str(monthly_limit_usd))
        if any(not x.is_finite() or x<0 for x in (self.daily_limit,self.monthly_limit)):raise ValueError('INVALID_BUDGET')
        self.local_prices=(Decimal(str(local_cost_input_usd_per_m)),Decimal(str(local_cost_output_usd_per_m))) if local_cost_input_usd_per_m is not None and local_cost_output_usd_per_m is not None else None
        with self._db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS certifications(
              role_id TEXT NOT NULL, model_id TEXT NOT NULL,
              task_set TEXT NOT NULL, min_quality REAL NOT NULL,
              measured_quality REAL NOT NULL, completed_at TEXT NOT NULL,
              valid_until TEXT NOT NULL, status TEXT NOT NULL,
              PRIMARY KEY(role_id,model_id,task_set)
            );
            CREATE TABLE IF NOT EXISTS model_reservations(
              request_id TEXT PRIMARY KEY, role_id TEXT NOT NULL,
              model_id TEXT NOT NULL, cost_cents INTEGER NOT NULL,
              reserved_at TEXT NOT NULL, status TEXT NOT NULL
            );
            ''')
            cols={r[1] for r in c.execute('PRAGMA table_info(model_reservations)')}
            if 'cost_microusd' not in cols:
                c.execute('ALTER TABLE model_reservations ADD COLUMN cost_microusd INTEGER')
                c.execute('UPDATE model_reservations SET cost_microusd=cost_cents*10000')
            certcols={r[1] for r in c.execute('PRAGMA table_info(certifications)')}
            if 'provenance_json' not in certcols:c.execute('ALTER TABLE certifications ADD COLUMN provenance_json TEXT')

    @contextmanager
    def _db(self):
        c=sqlite3.connect(self.path,timeout=15,isolation_level=None)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        try:
            yield c
            if c.in_transaction: c.commit()
        except Exception:
            if c.in_transaction: c.rollback()
            raise
        finally:
            c.close()

    def certify(self, role_id, model_id, task_set, measured, minimum, *, at,valid_until, provenance):
        if not provenance or not provenance.get('external_eval_report') or not provenance.get('locked_testset_hash'):
            raise ValueError('EXTERNAL_EVALUATION_REQUIRED')
        if role_id not in self.roles or model_id not in self.registry: raise ValueError('UNKNOWN_ROLE_OR_MODEL')
        if iso(valid_until)<=iso(at): raise ValueError('EXPIRED_CERTIFICATION')
        measured,minimum=float(measured),float(minimum)
        if not all(math.isfinite(x) and 0<=x<=1 for x in (measured,minimum)) or minimum<=0:raise ValueError('INVALID_QUALITY_SCORE')
        passed=measured>=minimum
        with self._db() as c:
            c.execute('INSERT OR REPLACE INTO certifications(role_id,model_id,task_set,min_quality,measured_quality,completed_at,valid_until,status,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)',(role_id,model_id,task_set,float(minimum),float(measured),iso(at).isoformat(),iso(valid_until).isoformat(),'PASS' if passed else 'FAIL',json.dumps(provenance,sort_keys=True,allow_nan=False)))
        return passed

    def _quote(self, model_id, input_tokens, output_tokens, asof):
        model=self.registry[model_id]
        if model['provider']=='python':return Decimal(0)
        if model['provider']=='self_hosted':
            if self.local_prices is None:return None
            return (self.local_prices[0]*input_tokens+self.local_prices[1]*output_tokens)/1_000_000
        if model.get('billing_currency','USD')!='USD': return None
        try:
            checked=date.fromisoformat(model['verified_at'])
            if not 0<=(asof.date()-checked).days<=90:return None
        except (KeyError,ValueError,TypeError):return None
        if model.get('price_valid_through') and asof.date().isoformat()>model['price_valid_through']:
            if not model.get('next_price_input_usd_per_m'): return None
            inprice=model['next_price_input_usd_per_m']; outprice=model['next_price_output_usd_per_m']
        else:
            inprice=model['input_usd_per_m'];outprice=model['output_usd_per_m']
        if model.get('price_cap_input_tokens') and input_tokens>model['price_cap_input_tokens']:
            inprice=model['higher_price_input_usd_per_m'];outprice=model['higher_price_output_usd_per_m']
        return (Decimal(str(inprice))*input_tokens+Decimal(str(outprice))*output_tokens)/1_000_000

    def select_and_reserve(self, *, request_id, role_id, task_set, data_scope, at, input_tokens, output_tokens, provider_available=None):
        now=iso(at)
        if role_id not in self.roles: return {'status':'UNKNOWN_ROLE'}
        role=self.roles[role_id]
        if data_scope not in ('public_only','private_only','local_only'): return {'status':'INVALID_SCOPE'}
        if type(input_tokens) is not int or type(output_tokens) is not int or input_tokens<0 or output_tokens<0 or input_tokens>100000 or output_tokens>16000:return {'status':'INVALID_TOKENS'}
        if role['data_scope']!=data_scope:
            return {'status':'PRIVACY_SCOPE_MISMATCH'}
        opts=[role['primary_model']]+([role['fallback_model']] if role.get('fallback_model') else [])
        if role['primary_model']!='deterministic' and data_scope=='local_only':return {'status':'PRIVACY_SCOPE_MISMATCH'}
        if role['primary_model']=='deterministic':
            return {'status':'DETERMINISTIC','model':'deterministic','can_trade':False}
        viable=[]
        with self._db() as c:
            for model_id in opts:
                if model_id not in self.registry: continue
                model=self.registry[model_id]
                if provider_available is not None and not provider_available.get(model_id,False):continue
                if data_scope=='private_only' and model['data_scope'] not in ('private_only','local_only'):continue
                if data_scope=='public_only' and model['data_scope']!='public_only':continue
                effort_order={'none':0,'low':1,'medium':2,'high':3}
                if effort_order.get(model.get('max_effort'),-1)<effort_order.get(role.get('minimum_effort'),99):continue
                row=c.execute('SELECT status,valid_until,completed_at,provenance_json FROM certifications WHERE role_id=? AND model_id=? AND task_set=?', (role_id,model_id,task_set)).fetchone()
                if not row or not row['provenance_json'] or row['status']!='PASS' or iso(row['valid_until'])<now or iso(row['completed_at'])>now: continue
                price=self._quote(model_id,input_tokens,output_tokens,now)
                # No pretending local GPU is free; local model needs external capacity accounting.
                if price is None or not price.is_finite() or price<0: continue
                viable.append((price,model_id))
        if not viable:return {'status':'NO_CURRENT_CERTIFIED_MODEL','can_trade':False}
        price,model_id=min(viable,key=lambda x:x[0])
        # Micro-dollar accounting avoids rounding every tiny request up to a cent.
        if not price.is_finite() or price<0:return {'status':'INVALID_PRICE','can_trade':False}
        micros=int((price*1000000).to_integral_value(rounding='ROUND_CEILING'))
        cents=(micros+9999)//10000
        with self._db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                old=c.execute('SELECT * FROM model_reservations WHERE request_id=?',(request_id,)).fetchone()
                if old:
                    c.execute('COMMIT')
                    if old['role_id']!=role_id:
                        return {'status':'IDEMPOTENCY_CONFLICT','can_trade':False}
                    return {'status':'ALREADY_RESERVED','model':old['model_id'],'can_trade':False}
                stamp=now.isoformat()
                startday=now.date().isoformat()
                startmonth=startday[:7]
                day=c.execute('SELECT COALESCE(SUM(COALESCE(cost_microusd,cost_cents*10000)),0) AS v FROM model_reservations WHERE reserved_at>=? AND reserved_at<? AND status!=?',(startday+'T00:00:00+00:00',(now.date()+timedelta(days=1)).isoformat()+'T00:00:00+00:00','CANCELED')).fetchone()['v']
                month=c.execute("SELECT COALESCE(SUM(COALESCE(cost_microusd,cost_cents*10000)),0) AS v FROM model_reservations WHERE substr(reserved_at,1,7)=? AND status!='CANCELED'",(startmonth,)).fetchone()['v']
                if day+micros>int(self.daily_limit*1000000) or month+micros>int(self.monthly_limit*1000000):
                    c.execute('COMMIT');return {'status':'COST_BUDGET_BLOCK','can_trade':False}
                c.execute('INSERT INTO model_reservations(request_id,role_id,model_id,cost_cents,reserved_at,status,cost_microusd) VALUES(?,?,?,?,?,?,?)',(request_id,role_id,model_id,cents,stamp,'RESERVED',micros))
                c.execute('COMMIT')
            except Exception:
                c.execute('ROLLBACK');raise
        return {'status':'RESERVED','model':model_id,'max_reserved_usd':str(Decimal(micros)/1000000),'can_trade':False}
