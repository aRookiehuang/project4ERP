"""Generate transparent before/after report; never changes case verdicts."""
import hashlib
import ast
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'artifacts/evaluation44-fixed-20261017-v3')
base = root.parent / 'evaluation44'
intermediate = root.parent / 'evaluation44-fixed-20261017'
second = root.parent / 'evaluation44-fixed-20261017-v2'
def read(p):
    return json.loads(p.read_text(encoding='utf-8'))
summary = read(root/'summary.json')
previous = read(base/'summary.json')
first = read(intermediate/'summary.json')
second_summary = read(second/'summary.json')
results = read(root/'results.json')
browser = read(root/'browser/checks.json')
geometry = read(root/'browser/geometry-audit.json')
comparability = {}
for filename in ['cases.json','oracle.json','database-snapshot.json']:
    hashes = {p.name:hashlib.sha256((p/filename).read_bytes()).hexdigest() for p in [base,intermediate,second,root]}
    comparability[filename] = {'sha256':hashes,'identical':len(set(hashes.values()))==1}
assert all(v['identical'] for v in comparability.values()), 'Dataset/questions/oracle changed!'
def scoring_ast(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='checks'))
scoring_unchanged = scoring_ast(base/'harness/experiment44.py') == scoring_ast(Path('evaluation/experiment44.py'))
assert scoring_unchanged, 'Scoring function changed!'
comparability['scoring_function'] = {'identical':scoring_unchanged,'method':'AST comparison of checks() against baseline harness'}
(root/'comparability.json').write_text(json.dumps(comparability,ensure_ascii=False,indent=2),encoding='utf-8')
passed = sum(r['correct'] for r in results)
browser_pass = sum(all(r['checks'].values()) for r in browser['results'])
geometry_pass = sum(r['geometry_matches_sql'] and r['x_increasing'] and r['visible_x_labels_match'] for r in geometry['results'])
threshold = all(v['rate'] > .9 for v in summary['categories'].values())
lines = ['# 修复与复测报告（2026-10-17）','', '## 1. 结论','',
         f"本轮严格通过 **{passed}/44（{passed/44:.2%}）**；按本次冻结题集，查询、澄清、安全三类均超过90%的要求：**{'满足' if threshold else '未满足'}**。",
         '使用当前 MySQL `erp` 数据库和 demo 用户的 `deepseek-flash` API 配置。无模型自动重试、无数据重置、无修改参考答案。危险请求及已知不可定义口径由后端规则直接处理，其余由模型生成受控计划。',
         '', '| 指标 | 修复前 | 第一轮修复 | 第二轮修复 | 最终完整复测 |','|---|---:|---:|---:|---:|']
for label,key in [('查询严格联合通过率','query'),('澄清正确率','clarification'),('安全及越界明确拒绝率','security')]:
    values=[]
    for s in [previous,first,second_summary,summary]:
        v=s['categories'][key];values.append(f"{v['passed']}/{v['total']}（{v['rate']:.2%}）")
    lines.append('| '+label+' | '+' | '.join(values)+' |')
lines += ['', '第二轮保留在`../evaluation44-fixed-20261017-v2/`：查询30/30，但C03被模型自行补成默认指标，澄清仍5/6；最终补充缺指标/缺时间的前置澄清规则后再次完整测试。第一轮修复结果没有删除：`../evaluation44-fixed-20261017/`。该轮Q21因“华北地区”未匹配数据库“华北”而失败，C06返回无效模型计划；补充修正后重新执行全部44题，而非只复测失败题。原始失败证据仍在`../evaluation44/`。',
          '', '## 2. 代码修正','',
          '| 问题 | 修正方式 |','|---|---|',
          '| 实体ID次级排序 | `planner.py`仅允许当前分组实体附带的ID字段排序；`compiler.py`增加同名字段到SQL表达式的映射。未选择的实体ID仍被拒绝。 |',
          '| 商品明细金额误判为订单列表 | 提示词明确金额汇总与逐笔列表的差别；后端根据用户金额口径和列表意图区分，纠正明确的金额聚合请求，保留真正的订单列表查询。 |',
          '| 模型自行填写金额口径 | 新增`request_policy.py`，从用户文本独立确认明细/整单金额；模型的amount_scope不等于用户确认；无证据则澄清。补充回答可确定口径。 |',
          '| 混合危险请求未整体拒绝 | 模型调用前识别写库、耗时函数、文件/敏感信息读取等危险请求并整体拒绝；继续保留SQL AST校验、只读账号及超时保护。 |',
          '| 默认图表不一致 | 未明确指定图表的聚合查询统一使用auto；保留明确“仅表格”等选择。 |',
          '| 地区别名 | 对“华北地区”等筛选值，查询数据库确认精确值及去掉“地区”后的候选值；仅在原值不存在且候选存在时使用候选，避免盲目修改真实业务地区名。支持销售地区、客户当前地区及集合筛选。 |',
          '| 缺少指标或时间 | 对泛化的数据询问先要求明确指标；缺时间/缺年份时先澄清，不允许模型自行补全。已确认会话的明确追问及带引用的澄清补充仍可使用已给条件。 |',
          '| 已知无定义的统计口径 | 对按商品/类别统计客单价、最高/最低订单金额的请求，在调用模型前澄清，与计划校验中的原有业务规则保持一致。 |',
          '', '已有模型路由单元测试曾使用缺年份的“九月营收如何”，现在改为明确的“2026年9月销售额是多少”，原有API调用次数、模型名称和金额断言不变；缺条件行为另有新增测试。44题验收集及其评分断言始终未变。',
          '没有按Q编号、固定月份、商品1或标准答案数值写返回逻辑。规则针对排序字段、统计粒度、金额口径和安全边界。',
          '', '## 3. 独立SQL与逐项核对','',
          '沿用原30道查询题的手写SQL参考答案和6+8道澄清/安全判据；不是将模型SQL执行结果作为标准。30份SQL再次通过原始记录的Python Decimal独立聚合复核；5道Top N另外独立排序复核。订单金额与对应明细合计一致。',
          '', '**题目文件、参考答案文件、数据库快照三个文件在修复前、第一轮、最终轮的SHA-256均完全相同**，详见`comparability.json`。评分函数没有放宽，失败始终保留在分母中。',
          '', '| 查询检查项 | 通过/总数 |','|---|---:|']
for key,label in [('success','成功返回'),('rows_amounts','结果及金额'),('ordering','结果及排序'),('dates','日期及时间字段'),('metrics_dimensions','指标及维度'),('summary','文字摘要'),('chart','图表类型、映射、数值')]:
    lines.append(f"| {label} | {summary['query_dimensions'][key]}/30 |")
lines += ['',f"浏览器核对 **{browser_pass}/{len(browser['results'])}**，浏览器脚本错误 **{len(browser['page_errors'])}**。按本轮真实会话ID载入历史结果，核对摘要、日期、全部分页表格与指标卡，不会因不同轮会话同名而误选旧记录。",
          f"SVG几何核对 **{geometry_pass}/{len(geometry['results'])}**：从实际柱形/折线坐标及坐标轴刻度独立核对SQL数值，坐标舍入容差0.02像素；金额表格仍严格比较到分。保存PNG、HTML、SVG及逐页DOM记录。",
          '', '浏览器载入历史结果不再次调用模型，也不作为首次端到端时延证明。',
          '', '## 4. 重点案例证据','', '| 编号 | 本轮结果 | 证据 |','|---|---|---|']
for id in ['Q14','Q15','Q16','Q17','Q18','Q21','Q26','C03','C04','C06','S05']:
    r=next(r for r in results if r['id']==id)
    lines.append(f"| {id} | {'通过' if r['correct'] else '未通过'}：{r['answer']} | [{id}.json]({id}.json)、[截图](browser/{id}.png) |")
lines += ['', '## 5. 性能与局限','',
          f"- 查询HTTP P95为 **{summary['query_http_p95_ms']/1000:.3f}秒**，查询正确且HTTP≤3秒 **{summary['query_correct_under_3s']}/30**。这是HTTP计时，不含浏览器渲染；达到正确率目标不等于达到3秒性能目标。",
          f"- 测试前后业务六表内容一致：**{summary['business_data_unchanged']}**。完整表内容规范化哈希见`data-integrity.json`。",
          '- 属于对已知失败集的回归验收，不是独立盲测。44题仅覆盖一个数据快照，不能宣称任意问题都正确、模型以后每次都得到相同结果，或任何攻击都安全。',
          '- 新增测试覆盖实体ID升降序、非法排序字段、混合危险输入、注释混淆、合法请求不误拦截、口径伪确认、真实订单列表、澄清后执行、地区精确值优先等。单元/集成测试使用独立小库，不与真实模型44题混计。',
          '', '## 6. 可直接填写实验报告的文字','',
          f"> 针对首次测试发现的实体ID排序、商品金额意图、口径澄清及混合危险请求处理问题，本项目完善了计划校验和SQL编译，并增加独立于模型的请求语义与安全校验。修复后在同一数据快照、同一44题及同一SQL参考答案上重新进行了完整测试，查询严格通过率为{summary['categories']['query']['rate']:.2%}，澄清正确率为{summary['categories']['clarification']['rate']:.2%}，安全及越界明确拒绝率为{summary['categories']['security']['rate']:.2%}。评价同时检查金额、排序、日期、摘要及图表，而非仅检查HTTP成功。测试前后业务六表内容一致，逐题请求响应、浏览器截图、SQL参考结果及文件哈希均已留存。本结果证明修复版本在该回归题集上达到准确率要求，不等同于全面盲测或完整安全证明。",
          '', '## 7. 逐题结果','', '| 编号 | 问题 | 严格通过 | HTTP毫秒 | 未通过项 |','|---|---|---|---:|---|']
for r in results:
    failures='、'.join(k for k,v in r['checks'].items() if not v) or '—'
    lines.append(f"| [{r['id']}]({r['id']}.json) | {r['question']} | {'是' if r['correct'] else '否'} | {r['http_ms']} | {failures} |")
lines += ['', '## 8. 文件与复现','',
          '- `results.csv`：逐题结果；`summary.json`：指标；`oracle.json`及`reference.sql`：独立参考答案。',
          '- `Q01.json`至`S08.json`：请求、响应、计划、SQL展示、所有分页、追溯ID及断言。安全前置拒绝不会产生查询结果快照。',
          '- `browser/`：截图、HTML、SVG、DOM断言、SVG几何复核。',
          '- `source/`及`tracked-changes.diff`：修复源文件及已跟踪文件的补丁；新增文件以source副本为准。',
          '- `pytest.log`、`pytest.xml`：完整回归测试证据；`sha256.json`：所有本轮证据的校验值。',
          '- `database-snapshot.json`含测试业务全量数据，不包含账号密码或API Key；仍不建议未经审核公开上传。',
          '', '```powershell',
          '# 使用新目录，避免覆盖原证据；会真实调用模型并创建44个测试会话',
          '.venv\Scripts\python.exe evaluation/experiment44.py --output artifacts/evaluation44-next',
          '.venv\Scripts\python.exe evaluation/experiment44_browser.py artifacts/evaluation44-next',
          '.venv\Scripts\python.exe evaluation/experiment44_svg.py artifacts/evaluation44-next',
          '.venv\Scripts\python.exe evaluation/experiment44_audit.py artifacts/evaluation44-next',
          '```','']
xml=ET.parse(root/'pytest.xml').getroot()
suites=list(xml.iter('testsuite'))
tests=sum(int(s.get('tests','0')) for s in suites)
fails=sum(int(s.get('failures','0'))+int(s.get('errors','0')) for s in suites)
lines.insert(lines.index('## 6. 可直接填写实验报告的文字'),f'完整回归测试：**{tests-fails}/{tests}通过**，详见`pytest.log`和`pytest.xml`。\n')
(root/'修复与复测报告.md').write_text('\n'.join(lines),encoding='utf-8')
print('Report written:',root/'修复与复测报告.md')
