"""Inspect persisted experiment conversations in the real browser; no model re-queries."""
import json, os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from backend.browser import browser_launch_options
from backend.app.config import settings

def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else 'artifacts/evaluation44'); out=root/'browser'; out.mkdir(exist_ok=True)
    cases=json.loads((root/'cases.json').read_text(encoding='utf-8')); results=[]; errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(**browser_launch_options(channel=settings.browser_channel,executable_path=settings.browser_executable_path))
        page=browser.new_page(viewport={'width':1600,'height':1100},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8000'); page.get_by_label('用户名').fill('demo'); page.get_by_label('密码',exact=True).fill(os.environ.get('ERP_EVAL_PASSWORD',settings.demo_password))
        with page.expect_response(lambda r:r.url.endswith('/api/conversations') and r.request.method=='GET') as loaded:
            page.get_by_role('button',name='进入工作台').click()
        conversations=loaded.value.json()
        expect(page.locator('.conversation-link').first).to_be_visible()
        for c in cases:
            ev=json.loads((root/(c['id']+'.json')).read_text(encoding='utf-8')); d=ev.get('response',{}); check={}
            try:
                # Titles are not unique across reruns. Match the recorded conversation ID.
                index=next(i for i,v in enumerate(conversations) if v['id']==ev['conversation_id'])
                with page.expect_response(lambda r:r.url.endswith('/api/conversations/'+ev['conversation_id'])):
                    page.locator('.conversation-link').nth(index).click()
                if d.get('status')=='success':
                    card=page.locator('.result-card'); expect(card).to_have_count(1)
                    expect(card.locator('.answer')).to_have_text(d['answer'])
                    check['summary_matches_api']=True
                    scope=card.locator('.scope-strip').inner_text(); check['dates_match_api']=all(d['time_range'][x] in scope for x in ['start','end'])
                    # Inspect every table page, not just the initial 20 rows.
                    all_rows=[]; pages=[d]+ev.get('pages',[])
                    for index,payload in enumerate(pages):
                        if index:
                            card.get_by_role('button',name='下一页').click()
                            first=payload['rows'][0]; expect(card.locator('tbody tr').first.locator('td').first).to_have_text(str(first[d['columns'][0]['key']]) if first[d['columns'][0]['key']] is not None else '—')
                        expected=[[str(r[col['key']]) if r[col['key']] is not None else '—' for col in d['columns']] for r in payload['rows']]
                        actual=card.locator('tbody tr').evaluate_all('(rs)=>rs.map(r=>Array.from(r.querySelectorAll("td"),c=>c.textContent.trim()))')
                        if not payload['rows']: actual=[]
                        all_rows.append({'page':index+1,'matches_api':expected==actual,'rendered_cells':actual})
                    check['table_all_pages_match_api']=all(x['matches_api'] for x in all_rows)
                    spec=d.get('chart_spec',{}); svg=card.locator('.chart svg')
                    if spec.get('type')=='card':
                        values=card.locator('.metric-cards strong').all_text_contents()
                        check['metric_cards_match_api']=values==[str(d['rows'][0][col['key']]) if d['rows'][0][col['key']] is not None else '无有效数据' for col in d['columns']]
                    if spec.get('type') in ['bar','line','pie']:
                        expect(svg).to_be_visible(); check['svg_rendered']=True
                        (out/(c['id']+'.svg')).write_text(svg.evaluate('(e)=>e.outerHTML'),encoding='utf-8')
                        labels=svg.locator('text').all_text_contents()
                    else: check['non_plot_mode']=svg.count()==0; labels=[]
                    evidence={'checks':check,'table_pages':all_rows,'svg_text':labels}
                else:
                    expect(page.get_by_text(d.get('answer',''),exact=True).first).to_be_visible()
                    evidence={'checks':{'message_visible':True,'no_result_card':page.locator('.result-card').count()==0}}
                page.screenshot(path=str(out/(c['id']+'.png')),full_page=True)
                (out/(c['id']+'.html')).write_text(page.content(),encoding='utf-8')
            except Exception as exc: evidence={'checks':{'browser_completed':False},'error':str(exc)}
            evidence['id']=c['id']; results.append(evidence)
            (out/'checks.json').write_text(json.dumps({'results':results,'page_errors':errors,'scope':'Persisted live conversation rendering, not a new model call. DOM checked against recorded API; oracle comparison is in parent directory. SVG screenshot is visual evidence, not pixel-level correctness proof.'},ensure_ascii=False,indent=2),encoding='utf-8')
            print(c['id'],evidence['checks'],flush=True)
        browser.close()
if __name__=='__main__':main()
