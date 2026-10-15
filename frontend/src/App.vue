<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { api, setCsrf } from "./api";
import type { Conversation, Message, Result, User, Preferences } from "./types";
import ResultCard from "./components/ResultCard.vue";
import SettingsPanel from "./components/SettingsPanel.vue";

const user = ref<User | null>(null);
const username = ref("demo");
const password = ref("");
const loginError = ref("");
const conversations = ref<Conversation[]>([]);
const selected = ref("");
const messages = ref<Message[]>([]);
const question = ref("");
const error = ref("");
const busy = ref(false);
const preferences = ref<Preferences>();
const sourceId = ref("default");
const showSettings = ref(false);
const currentSource = computed(() => preferences.value?.databases.find(d => d.id === sourceId.value));
const modelMode = computed(() => preferences.value?.model.effective_mode || health.value?.model_mode);
const loginBusy = ref(false);
const health = ref<{
  model_mode: string;
  database: string;
  data_coverage: string[];
  model_configured: boolean;
}>();
const adminData = ref("");
const showAdmin = ref(false);
const feed = ref<HTMLElement>();
const sidebarOpen = ref(false);
let controller: AbortController | undefined;
let queryStarted = 0;
let timingMessage = "";
const examples = [
  "2026 年 9 月销售额是多少？",
  "2026 年各商品类别的月度销售额趋势",
  "2026 年 9 月华东地区销售额最高的 5 个客户",
  "列出 2026 年 9 月华东地区已完成订单，按金额从高到低",
];
const title = computed(
  () =>
    conversations.value.find((c) => c.id === selected.value)?.title ||
    "销售分析工作台",
);
const pendingClarification = computed(() =>
  messages.value.at(-1)?.response?.status === "needs_clarification"
    ? messages.value.at(-1)?.response?.query_id
    : undefined,
);

async function bootstrap() {
  try {
    health.value = await api("/health/ready");
  } catch (e) {
    error.value = String(e);
  }
  try {
    user.value = await api<User>("/auth/me");
    setCsrf(user.value.csrf_token);
    await loadConversations();
  } catch {
    user.value = null;
  }
}
async function loadConversations() {
  conversations.value = await api<Conversation[]>("/conversations");
  await loadSettings();
}
async function loadSettings() {
  try { preferences.value = await api<Preferences>("/settings"); }
  catch (e) { error.value = e instanceof Error ? e.message : String(e); }
}
async function login() {
  loginBusy.value = true;
  loginError.value = "";
  try {
    user.value = await api<User>("/auth/login", "POST", {
      username: username.value,
      password: password.value,
    });
    setCsrf(user.value.csrf_token);
    password.value = "";
    await loadConversations();
  } catch (e) {
    loginError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loginBusy.value = false;
  }
}
async function logout() {
  controller?.abort();
  await api("/auth/logout", "POST");
  user.value = null;
  selected.value = "";
  messages.value = [];
  setCsrf("");
  preferences.value = undefined;
  sourceId.value = "default";
  showSettings.value = false;
}
function newConversation() {
  if (busy.value) return;
  selected.value = "";
  messages.value = [];
  error.value = "";
  sidebarOpen.value = false;
}
async function choose(id: string) {
  if (busy.value) return;
  selected.value = id;
  messages.value = [];
  error.value = "";
  sidebarOpen.value = false;
  try {
    const data = await api<{ messages: Message[]; source_id: string }>(`/conversations/${id}`);
    if (selected.value === id) { messages.value = data.messages; sourceId.value = data.source_id; }
  } catch (e) {
    error.value = String(e);
  }
}
async function scrollDown() {
  await nextTick();
  feed.value?.scrollTo({ top: feed.value.scrollHeight, behavior: "smooth" });
}
async function send() {
  if (!question.value.trim() || busy.value) return;
  const text = question.value.trim();
  busy.value = true;
  error.value = "";
  queryStarted = performance.now();
  const clarificationRef = pendingClarification.value;
  let conversationId = selected.value;
  const localId = crypto.randomUUID();
  try {
    if (!conversationId) {
      const created = await api<Conversation>("/conversations", "POST", {
        title: text.slice(0, 40),
        source_id: sourceId.value,
      });
      conversationId = created.id;
      selected.value = created.id;
      conversations.value.unshift(created);
    }
    question.value = "";
    const entry: Message = { id: localId, question: text, status: "running" };
    messages.value.push(entry);
    await scrollDown();
    controller = new AbortController();
    const result = await api<Result>(
      `/conversations/${conversationId}/queries`,
      "POST",
      {
        question: text,
        idempotency_key: localId,
        clarification_ref: clarificationRef,
      },
      controller.signal,
    );
    if (selected.value !== conversationId) return;
    const message = messages.value.find((m) => m.id === localId);
    if (message) {
      message.response = result;
      message.status = result.status;
      timingMessage = localId;
    }
    await scrollDown();
  } catch (e) {
    if (selected.value === conversationId) {
      const entry = messages.value.find((m) => m.id === localId);
      const answer =
        e instanceof Error && e.name === "AbortError"
          ? "查询已取消，可修改后重新发送。"
          : e instanceof Error
            ? e.message
            : String(e);
      if (entry) {
        entry.status = "failed";
        entry.response = { status: "failed", answer };
      } else error.value = answer;
      question.value = text;
    }
  } finally {
    busy.value = false;
    controller = undefined;
  }
}
function resultReady(id: string) {
  if (id !== timingMessage) return;
  const elapsed = performance.now() - queryStarted;
  window.dispatchEvent(
    new CustomEvent("erp:query-complete", {
      detail: { messageId: id, elapsedMs: elapsed },
    }),
  );
  performance.measure("erp-query-complete", {
    start: queryStarted,
    end: performance.now(),
  });
  timingMessage = "";
}
function keydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send();
  }
}
async function admin(kind: string) {
  showAdmin.value = true;
  try {
    adminData.value = JSON.stringify(await api(`/admin/${kind}`), null, 2);
  } catch (e) {
    adminData.value = String(e);
  }
}
onMounted(bootstrap);
</script>

<template>
  <div v-if="!user" class="login-shell">
    <div class="login-story">
      <div class="brand">
        <span class="brand-mark">观</span>
        <div>观数 <small>GUANSHU ANALYTICS</small></div>
      </div>
      <p class="eyebrow">ERP SALES INTELLIGENCE</p>
      <h1>让每一个业务问题，<br />都有数据回答。</h1>
      <p>用自然语言探索销售数据。<br />从一笔订单，到一份清晰的经营报告。</p>
      <div class="story-chart" aria-hidden="true">
        <i style="height: 35%"></i><i style="height: 52%"></i
        ><i style="height: 45%"></i><i style="height: 68%"></i
        ><i style="height: 57%"></i><i style="height: 84%"></i
        ><i style="height: 73%"></i><i style="height: 95%"></i>
      </div>
      <span class="story-foot">可追溯查询 · 可信数据 · 一键报告</span>
    </div>
    <form class="login-form" @submit.prevent="login">
      <span class="eyebrow">欢迎回来</span>
      <h2>登录分析工作台</h2>
      <p class="muted">使用预置演示账号，开始探索模拟销售数据。</p>
      <label
        >用户名<input
          v-model="username"
          autocomplete="username"
          required /></label
      ><label
        >密码<input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          placeholder="输入初始化时设置的密码" /></label
      ><button class="primary" :disabled="loginBusy">
        {{ loginBusy ? "登录中…" : "进入工作台 →" }}
      </button>
      <p v-if="loginError" class="error" role="alert">{{ loginError }}</p>
      <p class="login-note">
        演示账号：demo / analyst<br />默认演示密码见项目
        README，可通过环境变量修改。
      </p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>
  </div>
  <div v-else class="app-shell">
    <aside :class="['sidebar', { open: sidebarOpen }]">
      <div class="brand">
        <span class="brand-mark">观</span>
        <div>观数 <small>销售数据洞察</small></div>
      </div>
      <button class="new-chat" @click="newConversation">
        <span>＋</span> 新建分析会话
      </button>
      <div class="sidebar-label">最近会话</div>
      <nav>
        <button
          v-for="c in conversations"
          :key="c.id"
          :class="['conversation-link', { active: selected === c.id }]"
          @click="choose(c.id)"
        >
          <span>◷</span>{{ c.title }}
        </button>
        <p v-if="!conversations.length" class="sidebar-empty">
          你的分析记录将在这里保存
        </p>
      </nav>
      <div class="sidebar-bottom">
        <div class="source-card">
          <label for="database-source">查询数据库</label>
          <select id="database-source" v-model="sourceId" :disabled="busy || !!selected" style="width: 100%; margin: 10px 0; padding: 8px; border-radius: 6px">
            <option v-for="source in preferences?.databases" :key="source.id" :value="source.id">{{ source.name }} · {{ source.kind.toUpperCase() }}</option>
          </select>
          <p>{{ currentSource?.database }}</p>
          <small
            >{{ currentSource?.data_start }} — {{ currentSource?.data_end
            }}<br />结束日期不含在内</small
          >
          <p v-if="selected"><small>切换数据库请新建会话。</small></p>
        </div>
        <button :disabled="busy" @click="showSettings = true">数据库与模型设置</button>
        <div v-if="user.role === 'admin'" class="admin-actions">
          <button @click="admin('semantic-catalog')">语义目录</button
          ><button @click="admin('audit')">查询审计</button>
        </div>
        <div class="user-row">
          <span class="avatar">{{ user.username[0].toUpperCase() }}</span>
          <div>
            {{ user.username
            }}<small>{{ user.role === "admin" ? "管理员" : "分析用户" }}</small>
          </div>
          <button @click="logout" aria-label="退出登录">退出</button>
        </div>
      </div>
    </aside>
    <main>
      <header class="topbar">
        <button
          class="mobile-menu"
          aria-label="打开会话列表"
          @click="sidebarOpen = !sidebarOpen"
        >
          ☰
        </button>
        <div><span class="breadcrumb">工作空间 /</span> {{ title }}</div>
        <span
          :class="['mode-badge', { demo: modelMode === 'demo' }]"
          >{{
            modelMode === "demo"
              ? "规则演示模式"
              : preferences?.model.configured
                ? "模型 API 模式"
                : "模型待配置"
          }}</span
        >
      </header>
      <section ref="feed" class="feed" aria-live="polite">
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-icon">▥</div>
          <p class="eyebrow">从一个问题开始</p>
          <h1>今天，想了解哪些销售数据？</h1>
          <p>直接提问，获取可追溯的答案、图表与分析报告。</p>
          <div class="example-grid">
            <button
              v-for="(example, index) in examples"
              :key="example"
              @click="question = example"
            >
              <span>{{
                ["◈ 销售概览", "↗ 趋势洞察", "♧ 客户分析", "▤ 订单明细"][index]
              }}</span
              >{{ example }}<b>↗</b>
            </button>
          </div>
          <p class="welcome-hint">
            支持销售额、订单数、销量、客单价 · 查询只读执行
          </p>
        </div>
        <div class="message-flow">
          <div
            v-for="message in messages"
            :key="message.id"
            class="message-pair"
          >
            <div class="question-row">
              <span class="question-bubble">{{ message.question }}</span
              ><span class="avatar small">{{
                user.username[0].toUpperCase()
              }}</span>
            </div>
            <div class="assistant-row">
              <span class="assistant-avatar">观</span>
              <div class="assistant-content">
                <div class="assistant-label">
                  观数助手 <span>ERP ANALYST</span>
                </div>
                <div v-if="message.status === 'running'" class="thinking">
                  <span class="spinner"></span>正在理解问题并查询数据…
                </div>
                <ResultCard
                  v-else-if="message.response?.status === 'success'"
                  :result="message.response"
                  @ready="resultReady(message.id)"
                />
                <div
                  v-else
                  class="status-card"
                  :class="message.response?.status"
                >
                  <strong>{{
                    message.response?.status === "needs_clarification"
                      ? "需要补充一个条件"
                      : message.response?.status === "unsupported"
                        ? "当前范围说明"
                        : "本次查询未完成"
                  }}</strong>
                  <p>
                    {{ message.response?.answer || "查询未完成，请重新发送。" }}
                  </p>
                  <div
                    v-if="message.response?.status === 'needs_clarification'"
                    class="quick-options"
                  >
                    <button
                      v-for="option in ['本月', '本年', '全部历史']"
                      :key="option"
                      @click="question = option"
                    >
                      {{ option }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
      <div class="composer-wrap">
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <div v-if="pendingClarification" class="clarification-banner">
          下一条消息将补充到上一条待澄清问题
        </div>
        <form class="composer" @submit.prevent="send">
          <textarea
            v-model="question"
            @keydown="keydown"
            maxlength="1000"
            rows="2"
            :placeholder="
              pendingClarification
                ? '补充时间范围或所需指标…'
                : '例如：2026 年 9 月，华东地区销售额最高的 5 个客户？'
            "
            aria-label="输入分析问题"
          ></textarea>
          <div class="composer-bottom">
            <span>↵ 发送 <i>·</i> Shift + Enter 换行</span
            ><button
              v-if="busy"
              type="button"
              class="cancel-button"
              @click="controller?.abort()"
            >
              取消查询</button
            ><button v-else class="primary" :disabled="!question.trim()">
              开始分析 ↑
            </button>
          </div>
        </form>
        <p class="composer-note">
          {{
            modelMode === "demo"
              ? "当前使用有限规则解析器；配置模型 API 后可使用更灵活的自然语言查询。"
              : "答案依据数据库结果生成。请核对时间范围与指标口径。"
          }}
        </p>
      </div>
    </main>
    <SettingsPanel v-if="showSettings" :role="user.role" @close="showSettings = false" @changed="loadSettings" />
    <div
      v-if="showAdmin"
      class="modal-backdrop"
      @click.self="showAdmin = false"
    >
      <section
        class="admin-modal"
        role="dialog"
        aria-modal="true"
        aria-label="管理信息"
      >
        <button @click="showAdmin = false">关闭</button>
        <h2>系统管理</h2>
        <pre>{{ adminData }}</pre>
      </section>
    </div>
  </div>
</template>
