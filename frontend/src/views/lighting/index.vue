<template>
  <section class="page lighting-page" data-module="lighting">
    <header class="page-head">
      <div>
        <h2>景观照明调度台</h2>
        <p class="page-desc">
          开灯档位只按「亮灯时段 + 节气日历」口径判定：节庆要求优先于常规时段，超出允许亮灯时段一律拦截；
          电流超园区阈值单独告警；口径变更后亮灯排程自动重算，故障回路不参与排程。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="rebuild">按当前口径重算排程</button>
        <button class="btn" type="button" @click="loadAll">刷新</button>
      </div>
    </header>

    <!-- 当下口径快照：与「照明监控」页面读同一份接口数据 -->
    <div class="snapshot-bar" :class="snapshot['允许开灯'] ? 'is-on' : 'is-off'">
      <div class="snapshot-main">
        <strong>{{ snapshot['当前时间'] || '—' }}</strong>
        <span>节气季节：{{ snapshot['节气季节'] || '—' }}</span>
        <span class="snapshot-verdict">
          此刻口径：
          <em>{{ snapshot['允许开灯'] ? `允许开灯 · ${snapshot['口径档位名称']}（${snapshot['口径档位']}档）` : '不允许开灯' }}</em>
        </span>
        <span class="snapshot-source">依据：{{ snapshot['判定依据'] || '—' }}</span>
      </div>
      <div class="snapshot-meta">
        <span>口径版本 v{{ snapshot['口径版本'] || 1 }}</span>
        <span>最近重算：{{ snapshot['最近重算'] || '—' }}</span>
        <span>重算原因：{{ snapshot['最近重算原因'] || '—' }}</span>
      </div>
    </div>
    <p class="verdict-reason">{{ snapshot['判定说明'] }}</p>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <i v-if="tab.badge" class="tab-badge">{{ tab.badge }}</i>
      </button>
    </div>

    <p v-if="message" class="form-msg" :class="messageOk ? 'ok' : 'error-text'">{{ message }}</p>

    <!-- 照明台账 -->
    <div v-if="activeTab === 'ledger'" class="tab-panel">
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">回路总数</span><strong class="stat-value">{{ ledger.length }}</strong></article>
        <article class="stat-card"><span class="stat-label">故障停用</span><strong class="stat-value">{{ faultCount }}</strong></article>
        <article class="stat-card"><span class="stat-label">电流超限</span><strong class="stat-value">{{ overCurrentCount }}</strong></article>
        <article class="stat-card"><span class="stat-label">口径核对</span>
          <strong class="stat-value" :class="consistency['一致'] ? '' : 'error-text'">{{ consistency['一致'] ? '一致' : '不一致' }}</strong>
        </article>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>回路编号</th><th>回路名称</th><th>园区</th><th>回路状态</th>
            <th>当前电流A</th><th>园区上限A</th><th>电流校核</th>
            <th>当前档位</th><th>档位来源</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="row['回路编号']" :class="{ 'row-fault': row['回路状态'] === '故障', 'row-over': row['电流是否超限'] }">
            <td>{{ row['回路编号'] }}</td>
            <td>{{ row['回路名称'] }}</td>
            <td>{{ row['园区'] }}</td>
            <td>{{ row['回路状态'] }}</td>
            <td>{{ fmt(row['当前电流A']) }}</td>
            <td>{{ fmt(row['电流上限A']) }}</td>
            <td>
              <span :class="row['电流是否超限'] ? 'tag tag-danger' : 'tag tag-ok'">
                {{ row['电流是否超限'] ? '超限' : '正常' }}
              </span>
            </td>
            <td>{{ row['当前档位名称'] }}（{{ row['当前档位'] }}档）</td>
            <td class="muted-cell">{{ row['档位来源'] }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openCurrent(row)">上报电流</button>
              <button class="link" type="button" @click="toggleFault(row)">
                {{ row['回路状态'] === '故障' ? '修复投运' : '标记故障' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="panel-note">台账「当前档位」直接取控制记录结论（单一数据源），与监控页面读到的档位同一份；核对版本 v{{ consistency['口径版本'] }}，不一致 {{ consistency['不一致条数'] }} 条。</p>
    </div>

    <!-- 亮灯排程 -->
    <div v-if="activeTab === 'schedule'" class="tab-panel">
      <form class="filter-bar" @submit.prevent="loadSchedules">
        <label class="filter-item"><span>日期</span><input v-model="scheduleFilter.date" placeholder="YYYY-MM-DD" /></label>
        <label class="filter-item"><span>回路编号</span><input v-model="scheduleFilter.circuit_no" placeholder="按回路编号" /></label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr><th>日期</th><th>园区</th><th>回路编号</th><th>回路名称</th><th>允许时段</th><th>档位</th><th>判定依据</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in schedules" :key="`${row['日期']}-${row['回路编号']}`">
            <td>{{ row['日期'] }}</td>
            <td>{{ row['园区'] }}</td>
            <td>{{ row['回路编号'] }}</td>
            <td>{{ row['回路名称'] }}</td>
            <td>{{ row['开始时间'] }} ~ {{ row['结束时间'] }}</td>
            <td><span class="tag" :class="gearTag(row['档位'])">{{ row['档位名称'] }}（{{ row['档位'] }}档）</span></td>
            <td class="muted-cell">{{ row['判定依据'] }}</td>
            <td>{{ row['状态'] }}</td>
            <td class="row-actions">
              <button class="link" type="button" :disabled="row['状态'] === '已下发'" @click="dispatchSchedule(row)">
                {{ row['状态'] === '已下发' ? `已下发 #${row['控制记录id']}` : '按时段下发' }}
              </button>
            </td>
          </tr>
          <tr v-if="!schedules.length"><td colspan="9" class="empty-state">该条件下暂无排程（故障回路不参与排程）</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 控制下发 -->
    <div v-if="activeTab === 'dispatch'" class="tab-panel">
      <form class="entry-form" @submit.prevent="submitDispatch">
        <label class="filter-item"><span>回路编号 *</span>
          <select v-model="dispatchForm['回路编号']">
            <option value="">请选择</option>
            <option v-for="c in circuits" :key="c['回路编号']" :value="c['回路编号']">
              {{ c['回路编号'] }} · {{ c['回路名称'] }}（{{ c['园区'] }}{{ c['回路状态'] === '故障' ? '·故障' : '' }}）
            </option>
          </select>
        </label>
        <label class="filter-item"><span>时段日期 *</span><input v-model="dispatchForm['时段日期']" placeholder="YYYY-MM-DD" /></label>
        <label class="filter-item"><span>下发时刻</span><input v-model="dispatchForm['时刻']" placeholder="HH:MM，默认现在" /></label>
        <button class="btn primary" type="submit">下发开灯指令</button>
      </form>
      <p class="panel-note">服务端按口径重新判定档位：超出允许亮灯时段或回路故障会被拦截并说明缘由；同一回路同一时段日期重复提交只生效一次。</p>
      <table class="data-table">
        <thead>
          <tr><th>记录#</th><th>回路编号</th><th>园区</th><th>时段日期</th><th>下发时间</th><th>生效档位</th><th>判定依据</th><th>状态</th><th>判定说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in controls" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ row['回路编号'] }}</td>
            <td>{{ row['园区'] }}</td>
            <td>{{ row['时段日期'] }}</td>
            <td>{{ row['下发时间'] }}</td>
            <td><span class="tag" :class="gearTag(row['档位'])">{{ row['档位名称'] }}（{{ row['档位'] }}档）</span></td>
            <td class="muted-cell">{{ row['判定依据'] }}</td>
            <td>{{ row['状态'] }}</td>
            <td class="muted-cell">{{ row['判定说明'] }}</td>
          </tr>
          <tr v-if="!controls.length"><td colspan="9" class="empty-state">暂无控制记录</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 判定标准 -->
    <div v-if="activeTab === 'criteria'" class="tab-panel">
      <h3>节气常规亮灯窗口</h3>
      <table class="data-table">
        <thead><tr><th>季节（按节气切换）</th><th>开始时间</th><th>结束时间</th><th>档位</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="w in windows" :key="w.id">
            <td>{{ w['季节'] }}</td>
            <td><input v-model="w['开始时间']" class="cell-input" /></td>
            <td><input v-model="w['结束时间']" class="cell-input" /></td>
            <td>
              <select v-model.number="w['档位']" class="cell-input">
                <option :value="1">1 基础</option>
                <option :value="2">2 常规</option>
                <option :value="3">3 满档</option>
              </select>
            </td>
            <td class="row-actions"><button class="link" type="button" @click="saveWindow(w)">保存并重算排程</button></td>
          </tr>
        </tbody>
      </table>

      <h3>节庆亮灯日历（与常规冲突时节庆优先）</h3>
      <form class="entry-form" @submit.prevent="submitFestival">
        <label class="filter-item"><span>节庆名称 *</span><input v-model="festivalForm['节庆名称']" /></label>
        <label class="filter-item"><span>开始日期 *</span><input v-model="festivalForm['开始日期']" placeholder="YYYY-MM-DD" /></label>
        <label class="filter-item"><span>结束日期 *</span><input v-model="festivalForm['结束日期']" placeholder="YYYY-MM-DD" /></label>
        <label class="filter-item"><span>开始时间 *</span><input v-model="festivalForm['开始时间']" placeholder="HH:MM" /></label>
        <label class="filter-item"><span>结束时间 *</span><input v-model="festivalForm['结束时间']" placeholder="HH:MM" /></label>
        <label class="filter-item"><span>档位 *</span>
          <select v-model.number="festivalForm['档位']">
            <option :value="1">1 基础</option>
            <option :value="2">2 常规</option>
            <option :value="3">3 满档</option>
          </select>
        </label>
        <button class="btn primary" type="submit">新增节庆并重算</button>
      </form>
      <table class="data-table">
        <thead><tr><th>节庆名称</th><th>日期范围</th><th>亮灯时段</th><th>档位</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in festivals" :key="f.id">
            <td>{{ f['节庆名称'] }}</td>
            <td>{{ f['开始日期'] }} ~ {{ f['结束日期'] }}</td>
            <td>{{ f['开始时间'] }} ~ {{ f['结束时间'] }}</td>
            <td><span class="tag tag-fest">{{ gearLabel(f['档位']) }}（{{ f['档位'] }}档）</span></td>
            <td class="row-actions"><button class="link danger" type="button" @click="removeFestival(f)">删除并重算</button></td>
          </tr>
        </tbody>
      </table>
      <p class="panel-note">以上任一口径变更，系统都会自动重算未来 7 天已有亮灯排程；已下发记录保留，排程档位按新口径刷新。</p>
    </div>

    <!-- 园区阈值 -->
    <div v-if="activeTab === 'park'" class="tab-panel">
      <table class="data-table">
        <thead><tr><th>园区编号</th><th>园区名称</th><th>电流上限 A（各园区独立）</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="p in parks" :key="p.id">
            <td>{{ p['园区编号'] }}</td>
            <td>{{ p['园区名称'] }}</td>
            <td><input v-model.number="p['电流上限A']" class="cell-input" type="number" step="0.1" min="0" /></td>
            <td class="row-actions"><button class="link" type="button" @click="savePark(p)">保存并重新巡检告警</button></td>
          </tr>
        </tbody>
      </table>
      <p class="panel-note">阈值调低后超限回路会立刻单独产生告警；电流回落到阈值以内，未处理告警自动转为已恢复。</p>
    </div>

    <!-- 电流告警 -->
    <div v-if="activeTab === 'alarm'" class="tab-panel">
      <table class="data-table">
        <thead><tr><th>告警编号</th><th>园区</th><th>回路编号</th><th>回路名称</th><th>当前电流A</th><th>阈值A</th><th>告警时间</th><th>触发原因</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="a in alarms" :key="a.id" :class="{ 'row-over': a['状态'] === '未处理' }">
            <td>{{ a['告警编号'] }}</td>
            <td>{{ a['园区'] }}</td>
            <td>{{ a['回路编号'] }}</td>
            <td>{{ a['回路名称'] }}</td>
            <td class="error-text">{{ fmt(a['当前电流A']) }}</td>
            <td>{{ fmt(a['阈值A']) }}</td>
            <td>{{ a['告警时间'] }}</td>
            <td class="muted-cell">{{ a['触发原因'] }}{{ a['恢复说明'] ? '；' + a['恢复说明'] : '' }}</td>
            <td><span class="tag" :class="a['状态'] === '未处理' ? 'tag-danger' : 'tag-ok'">{{ a['状态'] }}</span></td>
            <td class="row-actions">
              <button v-if="a['状态'] === '未处理'" class="link" type="button" @click="resolveAlarm(a)">标记处理</button>
            </td>
          </tr>
          <tr v-if="!alarms.length"><td colspan="10" class="empty-state">暂无电流告警</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const message = ref('')
const messageOk = ref(false)

function notify(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function post(path: string, body: Record<string, unknown>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return response.json() as Promise<{ ok: boolean; message: string; entry?: Row }>
}
async function put(path: string, body: Record<string, unknown>) {
  const response = await request(path, { method: 'PUT', body: JSON.stringify(body) })
  return response.json() as Promise<{ ok: boolean; message: string; entry?: Row }>
}
async function del(path: string) {
  const response = await request(path, { method: 'DELETE' })
  return response.json() as Promise<{ ok: boolean; message: string }>
}

// ---------- 数据 ----------
const snapshot = ref<Row>({})
const ledger = ref<Row[]>([])
const circuits = ref<Row[]>([])
const schedules = ref<Row[]>([])
const controls = ref<Row[]>([])
const windows = ref<Row[]>([])
const festivals = ref<Row[]>([])
const parks = ref<Row[]>([])
const alarms = ref<Row[]>([])
const consistency = ref<Row>({})

const activeTab = ref('ledger')
const scheduleFilter = reactive({ date: '', circuit_no: '' })
const dispatchForm = reactive<Record<string, string>>({ '回路编号': '', '时段日期': '', '时刻': '' })
const festivalForm = reactive<Record<string, string | number>>({
  '节庆名称': '', '开始日期': '', '结束日期': '', '开始时间': '18:00', '结束时间': '23:00', '档位': 3,
})

const faultCount = computed(() => ledger.value.filter((r) => r['回路状态'] === '故障').length)
const overCurrentCount = computed(() => ledger.value.filter((r) => r['电流是否超限']).length)
const openAlarmCount = computed(() => alarms.value.filter((a) => a['状态'] === '未处理').length)
const tabs = computed(() => [
  { key: 'ledger', label: '照明台账', badge: 0 },
  { key: 'schedule', label: '亮灯排程', badge: 0 },
  { key: 'dispatch', label: '控制下发', badge: 0 },
  { key: 'criteria', label: '判定标准', badge: 0 },
  { key: 'park', label: '园区阈值', badge: 0 },
  { key: 'alarm', label: '电流告警', badge: openAlarmCount.value },
])

function fmt(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toFixed(1)
}
function gearLabel(gear: unknown) {
  return { 0: '关灯', 1: '基础', 2: '常规', 3: '满档' }[Number(gear)] ?? '未知'
}
function gearTag(gear: unknown) {
  return { 1: 'tag-basic', 2: 'tag-normal', 3: 'tag-fest' }[Number(gear)] ?? ''
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as T
}

async function loadAll() {
  try {
    const [snap, led, sch, ctl, win, fes, prk, alm, chk, cir] = await Promise.all([
      getJson<Row>('/api/lighting/snapshot'),
      getJson<{ items: Row[] }>('/api/lighting/ledger'),
      getJson<{ items: Row[] }>('/api/lighting/schedules'),
      getJson<{ items: Row[] }>('/api/lighting/controls'),
      getJson<{ items: Row[] }>('/api/lighting/windows'),
      getJson<{ items: Row[] }>('/api/lighting/festivals'),
      getJson<{ items: Row[] }>('/api/lighting/parks'),
      getJson<{ items: Row[] }>('/api/lighting/alarms'),
      getJson<Row>('/api/lighting/consistency'),
      getJson<{ items: Row[] }>('/api/lighting/circuits'),
    ])
    snapshot.value = snap
    ledger.value = led.items
    schedules.value = sch.items
    controls.value = ctl.items
    windows.value = win.items
    festivals.value = fes.items
    parks.value = prk.items
    alarms.value = alm.items
    consistency.value = chk
    circuits.value = cir.items
  } catch (error) {
    notify(error instanceof Error ? error.message : '景观照明数据加载失败', false)
  }
}

async function loadSchedules() {
  const query = new URLSearchParams()
  if (scheduleFilter.date) query.set('date', scheduleFilter.date)
  if (scheduleFilter.circuit_no) query.set('circuit_no', scheduleFilter.circuit_no)
  const data = await getJson<{ items: Row[] }>(`/api/lighting/schedules?${query.toString()}`)
  schedules.value = data.items
}

// ---------- 排程下发 ----------
async function dispatchSchedule(row: Row) {
  const result = await post('/api/lighting/controls/dispatch', {
    '回路编号': row['回路编号'],
    '时段日期': row['日期'],
    '时刻': row['开始时间'],
  })
  notify(result.message, result.ok)
  await loadAll()
}

async function submitDispatch() {
  if (!dispatchForm['回路编号'] || !dispatchForm['时段日期']) {
    notify('请选择回路并填写时段日期', false)
    return
  }
  const result = await post('/api/lighting/controls/dispatch', { ...dispatchForm })
  notify(result.message, result.ok)
  if (result.ok) {
    dispatchForm['时刻'] = ''
  }
  await loadAll()
}

// ---------- 台账操作 ----------
async function openCurrent(row: Row) {
  const text = window.prompt(`上报「${row['回路编号']}」当前电流（A）`, String(row['当前电流A'] ?? ''))
  if (text === null) return
  const result = await post(`/api/lighting/circuits/${row.id}/current`, { '当前电流A': Number(text) })
  notify(result.message, result.ok)
  await loadAll()
}
async function toggleFault(row: Row) {
  const toFault = row['回路状态'] !== '故障'
  const result = await post(`/api/lighting/circuits/${row.id}/status`, {
    '回路状态': toFault ? '故障' : '正常',
  })
  notify(result.message, result.ok)
  await loadAll()
}

// ---------- 判定标准 ----------
async function saveWindow(w: Row) {
  const result = await put(`/api/lighting/windows/${w.id}`, {
    '开始时间': w['开始时间'], '结束时间': w['结束时间'], '档位': w['档位'],
  })
  notify(result.message, result.ok)
  await loadAll()
}
async function submitFestival() {
  const result = await post('/api/lighting/festivals', { ...festivalForm })
  notify(result.message, result.ok)
  if (result.ok) {
    festivalForm['节庆名称'] = ''
    festivalForm['开始日期'] = ''
    festivalForm['结束日期'] = ''
  }
  await loadAll()
}
async function removeFestival(f: Row) {
  if (!window.confirm(`确认删除节庆「${f['节庆名称']}」？删除后排程将自动重算。`)) return
  const result = await del(`/api/lighting/festivals/${f.id}`)
  notify(result.message, result.ok)
  await loadAll()
}
async function rebuild() {
  const result = await post('/api/lighting/criteria/rebuild', { '原因': '值班员在调度台手动重算' })
  notify(result.message, result.ok)
  await loadAll()
}

// ---------- 园区阈值 / 告警 ----------
async function savePark(p: Row) {
  const result = await post(`/api/lighting/parks/${p.id}/threshold`, { '电流上限A': p['电流上限A'] })
  notify(result.message, result.ok)
  await loadAll()
}
async function resolveAlarm(a: Row) {
  const result = await post(`/api/lighting/alarms/${a.id}/resolve`, {})
  notify(result.message, result.ok)
  await loadAll()
}

onMounted(loadAll)
</script>

<style scoped>
.lighting-page .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin: 12px 0; flex-wrap: wrap; }
.tab { border: 1px solid var(--border); border-bottom: none; background: #f1f5f9; padding: 6px 14px; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 13px; position: relative; }
.tab.active { background: #fff; color: var(--brand); font-weight: 600; }
.tab-badge { font-style: normal; background: #b42318; color: #fff; border-radius: 10px; font-size: 11px; padding: 0 6px; margin-left: 4px; }
.tab-panel h3 { font-size: 14px; margin: 16px 0 8px; }
.snapshot-bar { display: flex; justify-content: space-between; gap: 12px; border: 1px solid var(--border); border-left-width: 4px; border-radius: 8px; background: #fff; padding: 10px 14px; flex-wrap: wrap; }
.snapshot-bar.is-on { border-left-color: #15803d; }
.snapshot-bar.is-off { border-left-color: #b42318; }
.snapshot-main { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.snapshot-main strong { font-size: 16px; }
.snapshot-verdict em { font-style: normal; color: #15803d; font-weight: 600; }
.is-off .snapshot-verdict em { color: #b42318; }
.snapshot-meta { display: flex; flex-direction: column; font-size: 12px; color: var(--muted); text-align: right; }
.verdict-reason { font-size: 12px; color: var(--muted); margin: 6px 2px 0; }
.panel-note { font-size: 12px; color: var(--muted); margin: 8px 2px; }
.muted-cell { color: var(--muted); font-size: 12px; }
.entry-form { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.cell-input { width: 100px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; }
.tag { display: inline-block; border-radius: 4px; padding: 1px 8px; font-size: 12px; background: #e2e8f0; }
.tag-ok { background: #dcfce7; color: #15803d; }
.tag-danger { background: #fee2e2; color: #b42318; }
.tag-basic { background: #fef9c3; color: #854d0e; }
.tag-normal { background: #dbeafe; color: #1e40af; }
.tag-fest { background: #fae8ff; color: #86198f; }
.row-over { background: #fff5f5; }
.row-fault { background: #f8fafc; color: var(--muted); }
.link.danger { color: #b42318; }
.link:disabled { color: #94a3b8; cursor: default; }
.form-msg.ok { color: #15803d; }
.form-msg { font-size: 13px; margin: 4px 0; }
</style>
