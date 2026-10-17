import json,sys,hashlib
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path.cwd()))
from evaluation.experiment44 import python_reference, reference_sql
from backend.app.config import settings
from sqlalchemy import create_engine,text
root=Path(sys.argv[1] if len(sys.argv)>1 else 'artifacts/evaluation44'); tables=json.loads((root/'database-snapshot.json').read_text(encoding='utf-8'))
for o in tables['orders']: o['paid_amount']=Decimal(o['paid_amount'])
for i in tables['order_items']:
    i['line_paid_amount']=Decimal(i['line_paid_amount']); i['unit_price']=Decimal(i['unit_price'])
cs=json.loads((root/'cases.json').read_text(encoding='utf-8')); oracle=json.loads((root/'oracle.json').read_text(encoding='utf-8')); ranks=[]
for c in cs:
    if c.get('rank'):
        rows=python_reference(c,tables); dim=c['dim']; m=c['metrics'][0]
        rows.sort(key=lambda r:r.get(dim+'_id',r[dim]))
        rows.sort(key=lambda r:Decimal(str(r[m])),reverse=not c['asc'])
        ranks.append({'id':c['id'],'independent_top_n_match':rows[:c['rank']]==oracle[c['id']]['rows'],'rows':rows[:c['rank']]})
line_totals={}
for i in tables['order_items']: line_totals[i['order_id']]=line_totals.get(i['order_id'],Decimal(0))+i['line_paid_amount']
mismatches=[o['id'] for o in tables['orders'] if o['paid_amount']!=line_totals.get(o['id'],Decimal(0))]
with create_engine(settings.business_database_url).connect() as db:
    grants=[r[0] for r in db.execute(text('SHOW GRANTS'))]
data={'rank_cross_check':ranks,'order_amount_equals_sum_of_items':not mismatches,'mismatched_order_ids':mismatches,'business_account_grants':grants,'code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for base in ['backend','frontend/src','frontend/dist','evaluation'] for p in Path(base).rglob('*') if p.is_file() and p.suffix in ['.py','.vue','.ts','.js','.css','.html']}}
(root/'additional-audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Independent ranks:',[(r['id'],r['independent_top_n_match']) for r in ranks]); print('Order/item mismatches:',len(mismatches)); print(grants)
