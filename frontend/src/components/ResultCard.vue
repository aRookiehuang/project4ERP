<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api";
import type { Result } from "../types";
import ChartView from "./ChartView.vue";

const props = defineProps<{ result: Result }>();
const emit = defineEmits<{ ready: [] }>();
const data = ref<Result>({ ...props.result });
const error = ref("");
const busy = ref("");
const includeSql = ref(false);
let alive = true;
const chart = computed(() => data.value.chart_spec);
const pages = computed(() =>
  Math.ceil((data.value.total_rows || 0) / (data.value.page_size || 20)),
);
const showChart = computed(() =>
  ["bar", "line", "pie"].includes(chart.value?.type || ""),
);
onMounted(() => {
  if (!showChart.value) requestAnimationFrame(() => emit("ready"));
});
onBeforeUnmount(() => {
  alive = false;
});

async function page(number: number) {
  try {
    data.value = await api<Result>(
      `/results/${data.value.result_id}?page=${number}`,
    );
  } catch (e) {
    error.value = String(e);
  }
}
async function changeChart(event: Event) {
  try {
    const result = await api<{ chart_spec: Result["chart_spec"] }>(
      `/results/${data.value.result_id}/chart`,
      "POST",
      { type: (event.target as HTMLSelectElement).value },
    );
    data.value.chart_spec = result.chart_spec;
  } catch (e) {
    error.value = String(e);
  }
}
async function exportReport(format: string) {
  if (busy.value) return;
  busy.value = format;
  error.value = "";
  try {
    const job = await api<{ id: string }>(
      `/results/${data.value.result_id}/exports`,
      "POST",
      { format, include_sql: includeSql.value },
    );
    const started = Date.now();
    while (alive && Date.now() - started < 180_000) {
      const status = await api<{ status: string; error?: string }>(
        `/exports/${job.id}`,
      );
      if (status.status === "succeeded") {
        const link = document.createElement("a");
        link.href = `/api/exports/${job.id}/download`;
        link.download = "";
        link.click();
        return;
      }
      if (["failed", "expired"].includes(status.status))
        throw new Error(status.error || "导出已过期，请重试。");
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    if (alive) error.value = "导出仍在排队，请确认导出工作进程正在运行。";
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = "";
  }
}
</script>

<template>
  <article class="result-card">
    <div class="result-top">
      <span class="success-label">✓ 查询完成</span
      ><span>{{ data.timing?.server_ms }} ms · 服务端</span>
    </div>
    <p class="answer">{{ data.answer }}</p>
    <div class="scope-strip">
      <span
        >◷ {{ data.time_range?.start }} 至
        {{ data.time_range?.end }}（不含结束日）</span
      ><span>人民币 / Asia·Shanghai</span>
    </div>
    <p v-if="data.truncated" class="notice">
      结果超过保存上限，仅保留前 1,000 条；此结果不是全量明细。
    </p>
    <div v-if="chart?.type === 'card'" class="metric-cards">
      <div v-for="column in data.columns" :key="column.key">
        <span>{{ column.label }}</span
        ><strong>{{ data.rows?.[0]?.[column.key] ?? "无有效数据" }}</strong
        ><small>{{ column.unit }}</small>
      </div>
    </div>
    <div v-if="showChart && chart" class="chart-panel">
      <ChartView
        :spec="chart"
        :columns="data.columns || []"
        @ready="emit('ready')"
      />
    </div>
    <p v-else-if="chart?.reason" class="muted chart-reason">
      {{ chart.reason }}
    </p>
    <div class="table-heading">
      <h3>
        查询结果
        <span
          >{{ data.total_rows }} {{ data.truncated ? "条已保存" : "行" }}</span
        >
      </h3>
      <select aria-label="图表类型" :value="chart?.type" @change="changeChart">
        <option value="bar">柱状图</option>
        <option value="line">折线图</option>
        <option value="pie">占比图</option>
        <option value="table">仅表格</option>
        <option value="card">指标卡</option>
      </select>
    </div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in data.columns" :key="c.key">
              {{ c.label }}<small v-if="c.unit">（{{ c.unit }}）</small>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in data.rows" :key="index">
            <td
              v-for="c in data.columns"
              :key="c.key"
              :class="{ numeric: ['decimal', 'integer'].includes(c.type) }"
            >
              {{ row[c.key] ?? "—" }}
            </td>
          </tr>
          <tr v-if="!data.rows?.length">
            <td :colspan="data.columns?.length">
              本条件下无数据，请核对时间与筛选条件。
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pagination" v-if="pages > 1">
      <button :disabled="data.page === 1" @click="page((data.page || 1) - 1)">
        上一页</button
      ><span>{{ data.page }} / {{ pages }}</span
      ><button
        :disabled="data.page === pages"
        @click="page((data.page || 1) + 1)"
      >
        下一页
      </button>
    </div>
    <details>
      <summary>查看指标口径与 SQL</summary>
      <p v-for="assumption in data.assumptions" :key="assumption">
        {{ assumption }}
      </p>
      <p v-for="metric in data.metric_definitions" :key="metric.label">
        {{ metric.label }}：{{ metric.definition }}
      </p>
      <pre>{{ data.sql_display }}</pre>
      <p class="muted">参数值隐藏；SQL 仅供追溯，不能在此编辑执行。</p>
    </details>
    <footer class="result-footer">
      <div class="snapshot-meta">
        快照 {{ data.snapshot_at?.slice(0, 19).replace("T", " ") }}<br />追溯
        {{ data.query_id?.slice(0, 8) }} · {{ data.versions?.data }}
      </div>
      <div class="export-actions">
        <label><input type="checkbox" v-model="includeSql" />附 SQL</label
        ><button :disabled="!!busy" @click="exportReport('docx')">
          {{ busy === "docx" ? "生成中…" : "↓ Word" }}</button
        ><button :disabled="!!busy" @click="exportReport('pdf')">
          {{ busy === "pdf" ? "生成中…" : "↓ PDF" }}
        </button>
      </div>
    </footer>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </article>
</template>
