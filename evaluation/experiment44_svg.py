"""Check actual rendered SVG geometry against SQL oracle, independently of chart_spec."""
import json,re,sys,xml.etree.ElementTree as ET
from pathlib import Path
root=Path(sys.argv[1] if len(sys.argv)>1 else 'artifacts/evaluation44')
oracles=json.loads((root/'oracle.json').read_text(encoding='utf-8'))
cs={c['id']:c for c in json.loads((root/'cases.json').read_text(encoding='utf-8'))}
num=r'-?\d+(?:\.\d+)?'
def numbers(s): return list(map(float,re.findall(num,s)))
results=[]
for file in sorted((root/'browser').glob('Q*.svg')):
    ident=file.stem; c=cs[ident]; rows=oracles[ident]['rows']; tree=ET.fromstring(file.read_text(encoding='utf-8')); elems=list(tree.iter())
    ticks=[]
    for e in elems:
        if e.tag.endswith('text') and e.get('fill')=='#54555a' and re.fullmatch(r'[\d,]+',e.text or ''):
            ticks.append((float(e.text.replace(',','')),numbers(e.get('transform',''))[-1]))
    lo,hi=min(ticks),max(ticks); scale=(hi[1]-lo[1])/(hi[0]-lo[0])
    expected_y=[lo[1]+(float(r[c['metrics'][0]])-lo[0])*scale for r in rows]
    if c['chart']=='line':
        paths=[e for e in elems if e.tag.endswith('path') and e.get('stroke')=='#0d9488' and e.get('fill')=='none' and not e.get('transform')]
        coords=numbers(paths[0].get('d')); xs=coords[::2]; ys=coords[1::2]
    else:
        paths=[e for e in elems if e.tag.endswith('path') and e.get('fill')=='#0d9488' and not e.get('transform')]
        vals=[numbers(e.get('d')) for e in paths]; xs=[v[0]+v[2]/2 for v in vals]; ys=[v[1]+v[5] for v in vals]
    errors=[abs(a-b) for a,b in zip(ys,expected_y)]
    labels=[e.text for e in elems if e.tag.endswith('text') and e.get('fill')=='#6d7f89']
    expected_labels=[str(r[c['dim']])+((' #'+str(r[c['dim']+'_id'])) if c['dim']+'_id' in r else '') for r in rows]
    result={'id':ident,'plotted_points':len(ys),'expected_points':len(rows),'geometry_matches_sql':len(ys)==len(rows) and max(errors,default=0)<.02,'max_y_error_pixels':max(errors,default=0),'x_increasing':xs==sorted(xs),'visible_x_labels_match':all(label in expected_labels for label in labels),'expected_values':[r[c['metrics'][0]] for r in rows],'observed_y':ys,'expected_y':expected_y}
    results.append(result)
(root/'browser'/'geometry-audit.json').write_text(json.dumps({'tolerance_pixels':.02,'note':'Single-series nonnegative linear axes only; values compared in pixel space because SVG rounds coordinates. API/table money remains exact to cents.','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
print([(r['id'],r['geometry_matches_sql'],r['visible_x_labels_match']) for r in results])
