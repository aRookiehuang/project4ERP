<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "../api";
import type { ModelSettings, Preferences } from "../types";

defineProps<{ role: string }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const dialog = ref<HTMLDialogElement>();
const busy = ref(false);
const loading = ref(true);
const error = ref("");
const message = ref("");
const savedKey = ref(false);
const databases = ref<string[]>([]);
const model = reactive({ mode: "server" as "server" | "demo" | "api", base_url: "", model: "", api_key: "", timeout_seconds: 30 });
const database = reactive({ name: "MySQL 业务库", host: "127.0.0.1", port: 3306, username: "query_reader", password: "", database: "", data_start: "2024-11-01", data_end: "2026-11-01" });

async function action(work: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = message.value = "";
  try { await work(); }
  catch (e) { error.value = e instanceof Error ? e.message : String(e); }
  finally { busy.value = false; }
}
function applyModel(value: ModelSettings) {
  Object.assign(model, { mode: value.mode, base_url: value.base_url, model: value.model, timeout_seconds: value.timeout_seconds, api_key: "" });
  savedKey.value = value.has_api_key;
}
async function saveModel() {
  await action(async () => {
    const value = await api<ModelSettings>("/settings/model", "PUT", model);
    applyModel(value);
    message.value = "模型设置已保存，下一次查询生效。";
    emit("changed");
  });
}
async function testModel() {
  await action(async () => {
    const value = await api<{ message: string }>("/settings/model/test", "POST", model);
    message.value = value.message;
  });
}
async function discover() {
  await action(async () => {
    const value = await api<{ databases: string[] }>("/settings/databases/discover", "POST", database);
    databases.value = value.databases;
    message.value = `找到 ${value.databases.length} 个可见数据库，请选择业务库。`;
  });
}
async function testDatabase() {
  await action(async () => {
    const value = await api<{ message: string }>("/settings/databases/test", "POST", database);
    message.value = value.message;
  });
}
async function saveDatabase() {
  await action(async () => {
    await api("/settings/databases", "POST", database);
    database.password = "";
    message.value = "数据库检查通过并已添加，可在新会话中选择。";
    emit("changed");
  });
}
onMounted(async () => {
  dialog.value?.showModal();
  await action(async () => {
    const value = await api<Preferences>("/settings");
    applyModel(value.model);
    loading.value = false;
  });
});
</script>

<template>
  <dialog ref="dialog" class="settings-dialog" aria-labelledby="settings-title" @cancel.prevent="!busy && emit('close')">
    <header class="settings-heading"><h2 id="settings-title">数据库与模型设置</h2><button :disabled="busy" aria-label="关闭设置" @click="emit('close')">关闭</button></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" class="settings-notice" role="status">{{ message }}</p>
    <p v-if="loading">正在读取设置…</p>
    <template v-else>
      <form @submit.prevent="saveModel">
        <h3>我的模型 API</h3>
        <p class="muted">设置仅对当前账号生效。支持 OpenAI 兼容的 Chat Completions 与 JSON 输出。</p>
        <fieldset :disabled="busy" class="settings-fields">
          <label>模型模式<select v-model="model.mode"><option value="server">使用服务器默认配置</option><option value="api">使用我的模型 API</option><option value="demo">规则演示模式</option></select></label>
          <template v-if="model.mode === 'api'">
            <label>API 地址（Base URL）<input v-model="model.base_url" type="url" required placeholder="https://example.com/v1" autocomplete="off" /></label>
            <small>填写接口前缀，系统自动追加 /chat/completions。</small>
            <label>模型名称<input v-model="model.model" required maxlength="200" placeholder="供应商提供的模型 ID" /></label>
            <label>API Key<input v-model="model.api_key" type="password" autocomplete="new-password" :placeholder="savedKey ? '已保存；留空保留原密钥' : '填写 API Key'" /></label>
            <small>更换 API 地址后需重新填写密钥。密钥不会回显。</small>
            <label>模型响应超时（秒）<input v-model.number="model.timeout_seconds" type="number" min="5" max="120" required /></label>
          </template>
          <div class="settings-actions"><button class="primary" type="submit">保存模型设置</button><button type="button" :disabled="model.mode === 'demo'" @click="testModel">测试模型连接</button></div>
          <small>测试会调用一次所选模型，可能产生供应商费用；测试成功不会自动保存。</small>
        </fieldset>
      </form>
      <form v-if="role === 'admin'" @submit.prevent="saveDatabase" class="database-form">
        <h3>添加共享 MySQL 数据库</h3>
        <p class="muted">连接会对本站所有已登录用户开放查询。请使用只读账号；所选库需包含本项目的六张 ERP 业务表。主机地址以运行后端的机器为准。</p>
        <fieldset :disabled="busy" class="settings-fields">
          <label>连接名称<input v-model="database.name" required maxlength="80" /></label>
          <div class="settings-columns"><label>主机<input v-model="database.host" required /></label><label>端口<input v-model.number="database.port" type="number" min="1" max="65535" required /></label></div>
          <div class="settings-columns"><label>数据库账号<input v-model="database.username" autocomplete="off" required /></label><label>数据库密码<input v-model="database.password" type="password" autocomplete="new-password" /></label></div>
          <button type="button" @click="discover">读取可选数据库</button>
          <label>数据库名称<input v-model="database.database" list="mysql-databases" required maxlength="64" placeholder="选择或填写数据库名称" /></label>
          <datalist id="mysql-databases"><option v-for="name in databases" :key="name" :value="name" /></datalist>
          <div class="settings-columns"><label>数据开始日期<input v-model="database.data_start" type="date" required /></label><label>数据结束日期（不含）<input v-model="database.data_end" type="date" required /></label></div>
          <small>日期用于“全部历史”查询范围，请按实际数据填写。</small>
          <div class="settings-actions"><button class="primary" type="submit">检查并添加数据库</button><button type="button" @click="testDatabase">测试数据库连接</button></div>
        </fieldset>
      </form>
      <p v-else class="muted database-form">数据库连接由管理员维护。你可以在侧栏选择已添加的数据库。</p>
    </template>
  </dialog>
</template>

<style scoped>
.settings-dialog { width: min(680px, calc(100vw - 24px)); max-height: calc(100dvh - 40px); border: 1px solid #dce5e9; border-radius: 16px; padding: 24px; color: #243746; }
.settings-dialog::backdrop { background: #172b3866; }
.settings-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.settings-heading h2 { margin: 0; font-size: 20px; }
.settings-fields { display: grid; gap: 12px; border: 0; padding: 0; min-width: 0; }
.settings-fields label { display: grid; gap: 6px; min-width: 0; }
.settings-fields input, .settings-fields select { width: 100%; min-width: 0; padding: 10px; border: 1px solid #dce5e9; border-radius: 8px; background: white; }
.settings-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.settings-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.settings-notice { padding: 12px; background: #e9f7f2; color: #076752; border-radius: 8px; }
.database-form { margin-top: 28px; padding-top: 22px; border-top: 1px solid #e4ebee; }
@media(max-width: 480px) { .settings-dialog { padding: 18px; } .settings-columns { grid-template-columns: 1fr; } }
</style>
