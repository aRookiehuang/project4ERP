# 评测说明

`run.py` 接收外部 JSONL 案例，检查状态、计划、结果、图表字段并记录 HTTP 耗时、失败和联合正确及时率。所有请求保留在分母；未完成请求在 P95 中按无穷值处理。无序结果采用多重集合比较，保留重复行。

示例结构（数据必须针对当前冻结快照独立计算，以下仅为微型测试数据的示例）：

```json
{"case_id":"dev-001","category":"single_aggregate","turns":[{"question":"2026 年 9 月销售额是多少？","ordered":true,"expected":{"status":"success","plan":{"metrics":["sales_amount"],"time_range":{"start":"2026-09-01","end":"2026-10-01"}},"rows":[{"sales_amount":"600.00"}],"chart_spec":{"type":"card"}}}]}
```

```bash
ERP_EVAL_PASSWORD=your-password python evaluation/run.py /path/to/frozen-cases.jsonl --concurrency 1
```

正式准确率评测应提供完整计划断言（含时间、筛选、指标、排序）、期望行和图表映射，不仅检查 status。需要按照原文档由独立验收人准备并冻结 300 个查询、60 个澄清和 80 个安全/越界问题；在三份数据快照上运行并保留每轮报告。这里没有生成或伪称已经存在独立盲测集。

HTTP 统计不包含浏览器渲染，不能用它证明 3 秒端到端达标。前端在表格和图表可用时发出 `erp:query-complete` 自定义事件，并记录 `erp-query-complete` Performance Measure；`browser_smoke.py` 可运行真实浏览器主流程并获取该计时。正式 1/5 并发、每组 1000 次与冷启动/导出干扰测试仍需真实 MySQL 和模型 API。
