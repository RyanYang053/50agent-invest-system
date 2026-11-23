"""License-based routing rules; defaults deny unknown supplier rights.

Policy is an explicit local entitlement snapshot, NOT legal advice or automatic
consent. New data contracts require operator verification.
"""
from __future__ import annotations

class LicenseGate:
    ACTIONS={'query_personal','index_persistent','embed_external','train_or_evaluate_model','redistribute'}
    def __init__(self, entitlements:dict):
        self.entitlements=entitlements
    def authorize(self,source_id:str,action:str,*,scope='personal'):
        if action not in self.ACTIONS:return {'status':'DENY','reason':'UNKNOWN_ACTION'}
        policy=self.entitlements.get(source_id)
        if not policy:return {'status':'DENY','reason':'UNVERIFIED_SOURCE_LICENSE'}
        if scope!='personal' and not policy.get('commercial_use',False):
            return {'status':'DENY','reason':'PERSONAL_LICENSE_ONLY'}
        allow=policy.get(action,False)
        return {'status':'ALLOW' if allow is True else 'DENY',
                'reason':'EXPLICIT_ENTITLEMENT' if allow is True else 'RIGHT_NOT_VERIFIED_OR_FORBIDDEN'}
