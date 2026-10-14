<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";
import type { ChartSpec, Column, Cell } from "../types";

const props = defineProps<{ spec: ChartSpec; columns: Column[] }>();
const emit = defineEmits<{ ready: [] }>();
const element = ref<HTMLDivElement>();
let instance: echarts.ECharts | undefined;
let observer: ResizeObserver | undefined;

async function render() {
  await nextTick();
  if (!element.value) return;
  if (!instance)
    instance = echarts.init(element.value, undefined, { renderer: "svg" });
  const { spec, columns } = props;
  const rows = spec.data || [];
  const dimension = spec.x || "";
  const key = (row: Record<string, Cell>, field: string) =>
    row[field + "_id"] == null
      ? String(row[field])
      : `${row[field]} #${row[field + "_id"]}`;
  const x = [...new Set(rows.map((row) => key(row, dimension)))];
  const series: echarts.SeriesOption[] = [];
  const metrics = spec.series || [];
  const units = [
    ...new Set(
      metrics.map(
        (metric) => columns.find((c) => c.key === metric)?.unit || "",
      ),
    ),
  ];
  for (const metric of metrics) {
    const column = columns.find((c) => c.key === metric);
    const groups = spec.group
      ? [...new Set(rows.map((row) => key(row, spec.group!)))]
      : [""];
    for (const group of groups) {
      series.push({
        name: `${group ? group + " · " : ""}${column?.label || metric}${column?.unit ? "（" + column.unit + "）" : ""}`,
        type: spec.type === "line" ? "line" : "bar",
        yAxisIndex: units.indexOf(column?.unit || ""),
        data: x.map((label) => {
          const row = rows.find(
            (r) =>
              key(r, dimension) === label &&
              (!spec.group || key(r, spec.group) === group),
          );
          return row?.[metric] == null ? null : Number(row[metric]);
        }),
        ...(spec.type === "line"
          ? { smooth: false, connectNulls: false, symbolSize: 6 }
          : { barMaxWidth: 38 }),
      });
    }
  }
  const option: echarts.EChartsOption = {
    animation: false,
    color: ["#0d9488", "#5b8def", "#eba94e", "#a78bdb", "#e58193"],
    textStyle: { fontFamily: "ERP Chinese, system-ui, sans-serif" },
    tooltip: { trigger: "axis", renderMode: "richText" },
    legend: { bottom: 0, type: "scroll", textStyle: { color: "#627581" } },
    grid: {
      top: 35,
      left: 65,
      right: units.length > 1 ? 65 : 25,
      bottom: 72,
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: x,
      axisLine: { lineStyle: { color: "#dce5e9" } },
      axisTick: { show: false },
      axisLabel: { color: "#6d7f89", rotate: x.length > 8 ? 30 : 0 },
    },
    yAxis: units.map((unit, index) => ({
      type: "value" as const,
      name: unit,
      position: index ? ("right" as const) : ("left" as const),
      offset: index > 1 ? 50 : 0,
      splitLine: { lineStyle: { color: "#edf1f3", type: "dashed" } },
    })),
    series,
  };
  if (spec.type === "pie") {
    delete option.xAxis;
    delete option.yAxis;
    option.tooltip = { trigger: "item", renderMode: "richText" };
    option.series = [
      {
        type: "pie",
        radius: ["40%", "68%"],
        center: ["50%", "44%"],
        data: rows.map((row) => ({
          name: key(row, dimension),
          value: Number(row[metrics[0]]),
        })),
      },
    ];
  }
  instance.setOption(option, true);
  requestAnimationFrame(() => emit("ready"));
}
onMounted(() => {
  render();
  observer = new ResizeObserver(() => instance?.resize());
  if (element.value) observer.observe(element.value);
});
watch(() => props.spec, render, { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  instance?.dispose();
});
</script>

<template>
  <div
    ref="element"
    class="chart"
    role="img"
    :aria-label="`${spec.type === 'line' ? '趋势' : '统计'}图；数值见下方表格`"
  />
</template>
