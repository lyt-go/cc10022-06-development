<template>
  <section class="page rework-page" data-module="quality_rework">
    <header class="page-head">
      <div>
        <h2>补值返工视图</h2>
        <p class="page-desc">
          把质量检查识别的缺失字段追到来源记录，按采集分区拆成已核 / 未核，
          值班只把已核分区里待补的字段派给负责人。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="recompute" type="button" :disabled="busy" @click="recompute">
          重算质量检查
        </button>
        <button class="btn" data-testid="revalidate" type="button" :disabled="busy" @click="revalidate">
          复验并关闭返工项
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">已核分区待办</span>
        <strong class="stat-value" data-testid="verified-open">{{ summary['已核分区待办'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">未核分区待办</span>
        <strong class="stat-value" data-testid="unverified-open">{{ summary['未核分区待办'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可派发字段</span>
        <strong class="stat-value" data-testid="dispatchable">{{ summary['可派发'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已关闭</span>
        <strong class="stat-value" data-testid="closed">{{ summary['已关闭'] ?? 0 }}</strong>
      </article>
    </div>

    <p v-if="message" class="notice" data-testid="toast">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="error">{{ errorMessage }}</p>

    <h3 class="section-title">分区核验情况</h3>
    <table class="data-table" data-testid="partition-table">
      <thead>
        <tr>
          <th>分区</th><th>核验状态</th><th>事项数</th><th>待派发</th>
          <th>已派发</th><th>可派发</th><th>待补字段</th><th>来源记录</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="part in view.partitions" :key="part.分区" :data-testid="`partition-${part.分区}`" :data-status="part.分区状态">
          <td>{{ part.分区 }}</td>
          <td>
            <span class="tag" :class="part.分区状态 === '已核分区' ? 'ok' : 'warn'">{{ part.分区状态 }}</span>
          </td>
          <td>{{ part.事项数 }}</td>
          <td>{{ part.待派发 }}</td>
          <td>{{ part.已派发 }}</td>
          <td>{{ part.可派发 }}</td>
          <td>{{ part.待补字段.join('、') || '—' }}</td>
          <td>{{ part.来源记录.join('、') || '—' }}</td>
        </tr>
        <tr v-if="!view.partitions.length">
          <td colspan="8" class="empty-state">暂无返工明细，可先重算质量检查</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">可派发字段</h3>
    <table class="data-table" data-testid="dispatchable-table">
      <thead>
        <tr><th>选择</th><th>字段</th><th>事项数</th><th>来源记录</th><th>负责人</th></tr>
      </thead>
      <tbody>
        <tr v-for="group in view.dispatchable_fields" :key="group.字段">
          <td>
            <input
              type="checkbox"
              :data-testid="`pick-${group.字段}`"
              :checked="pickedFields.has(group.字段)"
              @change="toggleField(group.字段)"
            />
          </td>
          <td>{{ group.字段 }}</td>
          <td>{{ group.事项数 }}</td>
          <td>{{ group.来源记录.join('、') }}</td>
          <td>{{ group.负责人.join('、') || '未指派' }}</td>
        </tr>
        <tr v-if="!view.dispatchable_fields.length">
          <td colspan="5" class="empty-state">当前没有可派发字段（未核分区不参与派发）</td>
        </tr>
      </tbody>
    </table>
    <div class="dispatch-bar">
      <label class="filter-item">
        <span>派给负责人</span>
        <input v-model="owner" data-testid="dispatch-owner" placeholder="例如：数据组-王敏" />
      </label>
      <button class="btn primary" data-testid="dispatch" type="button" :disabled="busy || !pickedIds.length" @click="dispatch">
        派发选中事项（{{ pickedIds.length }}）
      </button>
    </div>

    <h3 class="section-title">返工明细</h3>
    <table class="data-table" data-testid="rework-table">
      <thead>
        <tr>
          <th>返工编号</th><th>来源记录</th><th>待补字段</th><th>分区</th>
          <th>分区状态</th><th>负责人</th><th>状态</th><th>轮次</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in view.items"
          :key="item.id"
          :data-testid="`rework-${item.id}`"
          :data-status="item.状态"
          :class="{ selected: trace?.item.id === item.id }"
        >
          <td>{{ item.返工编号 }}</td>
          <td>
            <button class="link" type="button" :data-testid="`trace-${item.返工编号}`" @click="openTrace(item)">
              {{ item.来源记录 }}
            </button>
          </td>
          <td>{{ item.待补字段 }}</td>
          <td>{{ item.分区 }}</td>
          <td>{{ item.分区状态 }}</td>
          <td>{{ item.负责人 || '—' }}</td>
          <td>{{ item.状态 }}</td>
          <td>{{ item.轮次 }}</td>
          <td>
            <span class="muted-text">{{ blockingReason(item) || '可派发' }}</span>
          </td>
        </tr>
        <tr v-if="!view.items.length">
          <td colspan="9" class="empty-state">暂无返工明细</td>
        </tr>
      </tbody>
    </table>

    <section v-if="trace" class="trace-panel" data-testid="trace-panel">
      <header class="trace-head">
        <h3>{{ trace.返工编号 }} · {{ trace.来源记录 }} · 待补 {{ trace.待补字段 }}</h3>
        <button class="btn ghost" type="button" @click="trace = null">关闭追溯</button>
      </header>
      <dl class="trace-grid">
        <div><dt>原始值</dt><dd data-testid="trace-raw-value">{{ trace.原始值 || '（空）' }}</dd></div>
        <div><dt>当前源记录值</dt><dd data-testid="trace-current-value">{{ trace.当前字段值 || '（空）' }}</dd></div>
        <div><dt>分区 / 状态</dt><dd>{{ trace.分区 }} / {{ trace.分区状态 }}</dd></div>
        <div><dt>事项状态</dt><dd>{{ trace.状态 }}</dd></div>
        <div><dt>轮次</dt><dd>首次 {{ trace.轮次 }} 轮 · 最近 {{ trace.item.最近轮次 ?? trace.轮次 }} 轮</dd></div>
        <div><dt>关闭方式</dt><dd>{{ trace.关闭方式 || '—' }}</dd></div>
        <div class="trace-full">
          <dt>原始数据快照</dt>
          <dd><pre class="raw-json" data-testid="trace-raw-row">{{ prettyRaw }}</pre></dd>
        </div>
      </dl>
      <form v-if="trace.当前原始行" class="supplement-form" @submit.prevent="supplement">
        <label class="filter-item">
          <span>补记 {{ trace.待补字段 }}</span>
          <input v-model="supplementValue" :data-testid="`supplement-${trace.待补字段}`" :placeholder="`给 ${trace.来源记录} 补上${trace.待补字段}`" />
        </label>
        <button class="btn" type="submit" :disabled="busy || !supplementValue.trim()" data-testid="supplement-submit">
          补记原始行
        </button>
        <span class="muted-text">补记后重算，字段即可从返工名单中关闭</span>
      </form>
    </section>

    <h3 class="section-title">报告回查</h3>
    <div class="dispatch-bar">
      <label class="filter-item">
        <span>报告编号</span>
        <input v-model="reportId" data-testid="report-id" placeholder="例如：RPT-20261120" />
      </label>
      <button class="btn" type="button" :disabled="busy" data-testid="report-query" @click="loadReport">回查</button>
      <span v-if="reportResult" class="muted-text" data-testid="report-summary">
        共 {{ reportResult.items.length }} 条，已关闭 {{ reportResult.closed_items.length }} 条
      </span>
    </div>
    <table v-if="reportResult" class="data-table" data-testid="report-table">
      <thead>
        <tr><th>返工编号</th><th>来源记录</th><th>待补字段</th><th>状态</th><th>复验值</th><th>关闭时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in reportResult.items" :key="item.id" :data-testid="`report-row-${item.id}`">
          <td>{{ item.返工编号 }}</td>
          <td>{{ item.来源记录 }}</td>
          <td>{{ item.待补字段 }}</td>
          <td>{{ item.状态 }}</td>
          <td>{{ item.复验值 || '—' }}</td>
          <td>{{ item.关闭时间 || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>已核分区 {{ view.verified_partitions.length }} 个 · 未核分区 {{ view.unverified_partitions.length }} 个</span>
      <span>{{ busy ? '处理中…' : `实体模型：${entityModel}` }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  dispatchRework,
  loadReportRework,
  loadReworkView,
  recomputeQuality,
  revalidateRework,
  supplementSourceField,
  traceRework,
} from '@/api/backend-service'
import {
  blockingReason,
  dispatchableItems,
  type ReworkItem,
  type ReworkTrace,
  type ReworkView,
} from '@/domain/quality_rework'

const entityModel = 'customer'
const view = ref<ReworkView>({
  entity_model: entityModel,
  summary: {},
  partitions: [],
  verified_partitions: [],
  unverified_partitions: [],
  dispatchable_fields: [],
  verified_pending_fields: [],
  items: [],
})
const reportId = ref('RPT-20261120')
const reportResult = ref<{ items: ReworkItem[]; closed_items: ReworkItem[] } | null>(null)
const trace = ref<ReworkTrace | null>(null)
const supplementValue = ref('')
const owner = ref('')
const pickedFields = ref<Set<string>>(new Set())
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const summary = computed(() => view.value.summary)
const prettyRaw = computed(() =>
  trace.value ? JSON.stringify(trace.value.原始数据, null, 2) : '',
)
const pickedIds = computed(() => {
  const ids = new Set<number>()
  for (const item of dispatchableItems(view.value)) {
    if (pickedFields.value.has(item.待补字段)) ids.add(item.id)
  }
  return [...ids]
})

function toggleField(field: string) {
  const next = new Set(pickedFields.value)
  if (next.has(field)) next.delete(field)
  else next.add(field)
  pickedFields.value = next
}

async function refresh() {
  view.value = await loadReworkView(entityModel)
}

async function run(task: () => Promise<string>) {
  busy.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    message.value = await task()
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    busy.value = false
  }
}

function recompute() {
  void run(async () => {
    const result = await recomputeQuality(entityModel, reportId.value)
    const rework = result.rework
    return `重算完成：完备率 ${result.completeness_pct ?? 0}%，第 ${result.round ?? 1} 轮；新增 ${rework?.新增明细 ?? 0}，更新 ${rework?.更新明细 ?? 0}，跳过已关闭 ${rework?.跳过已关闭 ?? 0}`
  })
}

function revalidate() {
  void run(async () => {
    const result = await revalidateRework(entityModel)
    return `复验完成：关闭 ${result.closed} 条，仍待补 ${result.still_open} 条`
  })
}

function dispatch() {
  void run(async () => {
    const result = await dispatchRework(pickedIds.value, owner.value)
    const rejected = result.rejected.map((item) => `${item.id}（${item.reason}）`).join('、')
    pickedFields.value = new Set()
    return `已派发 ${result.dispatched_count} 条${rejected ? `；拒绝 ${rejected}` : ''}`
  })
}

async function openTrace(item: ReworkItem) {
  errorMessage.value = ''
  try {
    trace.value = await traceRework(item.id)
    supplementValue.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追溯失败'
  }
}

function supplement() {
  const current = trace.value
  if (!current) return
  void run(async () => {
    const result = await supplementSourceField(current.来源记录, current.待补字段, supplementValue.value.trim())
    return `${current.来源记录} 的${current.待补字段}已补记：${result.before || '（空）'} → ${result.after}`
  })
}

async function loadReport() {
  busy.value = true
  errorMessage.value = ''
  try {
    reportResult.value = await loadReportRework(reportId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告回查失败'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  // 先读现有视图；还没有明细时才重算，避免每次打开页面都写一轮统计。
  busy.value = true
  errorMessage.value = ''
  try {
    await refresh()
    if (!view.value.items.length) {
      const result = await recomputeQuality(entityModel, reportId.value)
      message.value = `已按当前原始行重算第 ${result.round ?? 1} 轮质量检查`
      await refresh()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '返工视图读取失败'
  } finally {
    busy.value = false
  }
})
</script>

<style scoped>
.section-title { margin: 20px 0 8px; font-size: 14px; }
.notice { color: #1a7f37; font-size: 13px; margin: 4px 0; }
.muted-text { color: var(--muted); font-size: 12px; }
.tag { padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.tag.ok { background: #e7f5ea; color: #1a7f37; }
.tag.warn { background: #fff4e5; color: #b25e09; }
.dispatch-bar { display: flex; gap: 12px; align-items: flex-end; margin: 10px 0; }
.selected { background: #f0f6ff; }
.trace-panel { border: 1px solid var(--border); border-radius: 8px; background: #fff; padding: 12px 14px; margin-top: 14px; }
.trace-head { display: flex; justify-content: space-between; align-items: center; }
.trace-head h3 { font-size: 14px; margin: 0; }
.trace-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin: 12px 0; }
.trace-grid dt { font-size: 12px; color: var(--muted); }
.trace-grid dd { margin: 2px 0 0; font-size: 13px; }
.trace-full { grid-column: 1 / -1; }
.raw-json { background: #0f172a; color: #e2e8f0; border-radius: 6px; padding: 10px; font-size: 12px; overflow-x: auto; margin: 0; }
.supplement-form { display: flex; gap: 12px; align-items: flex-end; border-top: 1px solid var(--border); padding-top: 10px; }
</style>
