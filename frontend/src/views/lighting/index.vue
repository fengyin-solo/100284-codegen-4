<template>
  <section class="page" data-module="lighting">
    <header class="page-head">
      <div>
        <h2>景观照明开关口径</h2>
        <p class="page-desc">按亮灯时段与节气日历判定开灯档位：节庆优先，超时段不许开灯并说明缘由；电流超园区上限单独告警；标准变更自动重算排程。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/lighting-monitor">打开亮灯监控页</RouterLink>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="lt-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="lt-tab"
        :class="{ active: activeTab === tab.key }"
        type="button"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <p v-if="message" class="lt-message" :class="messageOk ? 'ok' : 'error-text'">{{ message }}</p>

    <!-- 档位试算 / 手动下发 -->
    <div v-if="activeTab === 'decide'" class="lt-panel">
      <form class="filter-bar" @submit.prevent="runDecide">
        <label class="filter-item">
          <span>日期</span>
          <input v-model="decideForm.date" type="date" />
        </label>
        <label class="filter-item">
          <span>时刻</span>
          <input v-model="decideForm.clock" type="time" />
        </label>
        <button class="btn primary" type="submit">按口径试算</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>回路编号</th><th>园区</th><th>是否允许开灯</th><th>应开档位</th>
            <th>依据类型</th><th>依据</th><th>亮灯时段</th><th>判定缘由</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in decideRows" :key="row.回路编号">
            <td>{{ row.回路编号 }}</td>
            <td>{{ row.园区 }}</td>
            <td>
              <span :class="row.允许开灯 ? 'lt-gear on' : 'lt-gear off'">
                {{ row.允许开灯 ? '允许' : '不许' }}
              </span>
            </td>
            <td><span class="lt-gear" :class="`g${row.档位}`">{{ row.档位文本 }}</span></td>
            <td>{{ row.依据类型 }}</td>
            <td>{{ row.依据 }}</td>
            <td>{{ row.亮灯时段 }}</td>
            <td class="lt-reason">{{ row.缘由 }}</td>
            <td>
              <button
                class="link"
                type="button"
                :disabled="!row.允许开灯"
                :title="row.允许开灯 ? '按该时刻下发' : row.缘由"
                @click="issue(row)"
              >
                此刻下发
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 照明台账 -->
    <div v-else-if="activeTab === 'circuits'" class="lt-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>回路编号</th><th>回路名称</th><th>园区</th><th>回路状态</th>
            <th>电流上限(A)</th><th>当前电流(A)</th><th>当前档位结论</th><th>档位依据（取控制记录）</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in circuits" :key="row.id">
            <td>{{ row.回路编号 }}</td>
            <td>{{ row.回路名称 }}</td>
            <td>{{ row.园区 }}</td>
            <td>
              <span :class="row.回路状态 === '故障' ? 'lt-gear off' : 'lt-gear on'">{{ row.回路状态 }}</span>
              <div v-if="row.故障描述" class="lt-sub">{{ row.故障描述 }}</div>
            </td>
            <td>{{ row.电流上限 }}</td>
            <td :class="overLimit(row) ? 'error-text' : ''">{{ row.当前电流 ?? '—' }}</td>
            <td><span class="lt-gear" :class="`g${row.当前档位}`">{{ row.档位结论 }}</span></td>
            <td class="lt-reason">{{ row.档位依据 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="reportCurrent(row)">上报电流</button>
              <button v-if="row.回路状态 === '正常'" class="link" type="button" @click="markFault(row)">置故障</button>
              <button v-else class="link" type="button" @click="repair(row)">修复投运</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 亮灯排程 -->
    <div v-else-if="activeTab === 'schedules'" class="lt-panel">
      <form class="filter-bar" @submit.prevent="loadSchedules">
        <label class="filter-item">
          <span>查看日期</span>
          <input v-model="scheduleDate" type="date" />
        </label>
        <button class="btn" type="submit">查询排程</button>
        <label class="filter-item">
          <span>区间开始</span>
          <input v-model="genForm.start" type="date" />
        </label>
        <label class="filter-item">
          <span>区间结束</span>
          <input v-model="genForm.end" type="date" />
        </label>
        <button class="btn primary" type="button" @click="generateSchedules">按当前标准重算排程</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>日期</th><th>回路编号</th><th>园区</th><th>依据类型</th><th>依据</th>
            <th>开灯</th><th>关灯</th><th>应开档位</th><th>状态</th><th>判定说明</th><th>控制记录</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in schedules" :key="idx">
            <td>{{ row.日期 }}</td><td>{{ row.回路编号 }}</td><td>{{ row.园区 }}</td>
            <td>{{ row.依据类型 }}</td><td>{{ row.依据 }}</td>
            <td>{{ row.开灯时间 }}</td><td>{{ row.关灯时间 }}</td>
            <td><span class="lt-gear" :class="`g${row.应开档位}`">{{ row.档位文本 }}</span></td>
            <td>
              <span class="lt-gear" :class="scheduleStatusClass(row.状态)">{{ row.状态 }}</span>
            </td>
            <td class="lt-reason">{{ row.判定说明 }}</td>
            <td>{{ row.控制记录id ? `#${row.控制记录id}` : '—' }}</td>
          </tr>
          <tr v-if="!schedules.length"><td colspan="11" class="empty-state">该日期暂无排程，可按区间生成</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 控制记录 -->
    <div v-else-if="activeTab === 'controls'" class="lt-panel">
      <form class="filter-bar" @submit.prevent="loadControls">
        <label class="filter-item lt-check"><input v-model="controlsOnlyEffective" type="checkbox" /> 只看生效记录</label>
        <button class="btn" type="submit">刷新</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th><th>回路编号</th><th>园区</th><th>日期</th><th>时段</th>
            <th>档位</th><th>依据</th><th>判定说明</th><th>操作人</th><th>状态</th><th>下发时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in controls" :key="row.id">
            <td>{{ row.id }}</td><td>{{ row.回路编号 }}</td><td>{{ row.园区 }}</td>
            <td>{{ row.日期 }}</td><td>{{ row.开灯时间 }}-{{ row.关灯时间 }}</td>
            <td><span class="lt-gear" :class="`g${row.档位}`">{{ row.档位文本 }}</span></td>
            <td>{{ row.依据类型 }}·{{ row.依据 }}</td>
            <td class="lt-reason">{{ row.判定说明 }}</td>
            <td>{{ row.操作人 }}</td>
            <td>
              <span :class="row.生效 ? 'lt-gear on' : 'lt-gear off'">{{ row.状态 }}</span>
            </td>
            <td>{{ row.下发时间 }}</td>
          </tr>
          <tr v-if="!controls.length"><td colspan="11" class="empty-state">暂无控制记录</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 电流告警 -->
    <div v-else-if="activeTab === 'alarms'" class="lt-panel">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th><th>回路编号</th><th>回路名称</th><th>园区</th>
            <th>电流上限(A)</th><th>最新电流(A)</th><th>上报次数</th>
            <th>首次上报</th><th>最近上报</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in alarms" :key="row.id">
            <td>{{ row.id }}</td><td>{{ row.回路编号 }}</td><td>{{ row.回路名称 }}</td><td>{{ row.园区 }}</td>
            <td>{{ row.电流上限 }}</td>
            <td class="error-text">{{ row.最新电流 }}</td>
            <td>{{ row.上报次数 }}</td>
            <td>{{ row.首次上报 }}</td><td>{{ row.最近上报 }}</td>
            <td><span class="lt-gear off">{{ row.状态 }}</span></td>
            <td><button class="link" type="button" @click="resolveAlarm(row)">解除告警</button></td>
          </tr>
          <tr v-if="!alarms.length"><td colspan="11" class="empty-state">当前没有未解除的电流告警</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 判定标准：园区阈值 / 节气时段 / 节庆日历 -->
    <div v-else-if="activeTab === 'rules'" class="lt-panel">
      <h3 class="lt-h3">园区电流阈值（各园区单独设置）</h3>
      <table class="data-table">
        <thead><tr><th>园区</th><th>电流上限(A)</th><th>备注</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="park in parks" :key="park.id">
            <td>{{ park.园区名称 }}</td>
            <td><input v-model.number="parkDraft[park.id]" type="number" step="0.1" min="0" /></td>
            <td>{{ park.备注 }}</td>
            <td><button class="btn" type="button" @click="saveThreshold(park)">保存阈值</button></td>
          </tr>
        </tbody>
      </table>

      <h3 class="lt-h3">节气亮灯时段（常规口径，按立春/立夏/立秋/立冬切换）</h3>
      <table class="data-table">
        <thead><tr><th>季节</th><th>起始节气</th><th>开灯时间</th><th>关灯时间</th><th>开灯档位</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="rule in windowRules" :key="rule.id">
            <td>{{ rule.季节 }}季</td><td>{{ rule.起始节气 }}</td>
            <td><input v-model="rule.开灯时间" type="time" /></td>
            <td><input v-model="rule.关灯时间" type="time" /></td>
            <td>
              <select v-model.number="rule.开灯档位">
                <option :value="1">1 节能档</option>
                <option :value="2">2 常规档</option>
                <option :value="3">3 全开档</option>
              </select>
            </td>
            <td><button class="btn" type="button" @click="saveWindow(rule)">保存并重算排程</button></td>
          </tr>
        </tbody>
      </table>

      <h3 class="lt-h3">节庆日历（与常规时段冲突时，节庆口径优先）</h3>
      <table class="data-table">
        <thead><tr><th>节庆</th><th>开始</th><th>结束</th><th>开灯</th><th>关灯</th><th>档位</th><th></th></tr></thead>
        <tbody>
          <tr v-for="festival in festivals" :key="festival.id">
            <td>{{ festival.节庆名称 }}</td>
            <td>{{ festival.开始日期 }}</td><td>{{ festival.结束日期 }}</td>
            <td>{{ festival.开灯时间 }}</td><td>{{ festival.关灯时间 }}</td>
            <td>{{ festival.开灯档位 }} 档</td><td></td>
          </tr>
          <tr>
            <td><input v-model="festivalForm.节庆名称" placeholder="如：春节" /></td>
            <td><input v-model="festivalForm.开始日期" type="date" /></td>
            <td><input v-model="festivalForm.结束日期" type="date" /></td>
            <td><input v-model="festivalForm.开灯时间" type="time" /></td>
            <td><input v-model="festivalForm.关灯时间" type="time" /></td>
            <td>
              <select v-model.number="festivalForm.开灯档位">
                <option :value="1">1</option><option :value="2">2</option><option :value="3">3</option>
              </select>
            </td>
            <td><button class="btn primary" type="button" @click="saveFestival">新增节庆并重算</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>景观照明开关口径以判定服务为唯一来源：台账、排程、控制记录、监控页共用同一结论</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/lighting'

type Row = Record<string, any>

const tabs = [
  { key: 'decide', label: '档位判定' },
  { key: 'circuits', label: '照明台账' },
  { key: 'schedules', label: '亮灯排程' },
  { key: 'controls', label: '控制记录' },
  { key: 'alarms', label: '电流告警' },
  { key: 'rules', label: '判定标准' },
]
const activeTab = ref('decide')
const message = ref('')
const messageOk = ref(true)

function notify(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function post(path: string, values: Record<string, any>) {
  const res = await request(`${ENDPOINT}${path}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return res.json()
}

// ---- 试算 ----
const decideForm = reactive({ date: '2026-09-30', clock: '19:00' })
const decideRows = ref<Row[]>([])

async function runDecide() {
  const res = await request(`${ENDPOINT}/decide`, {
    method: 'POST',
    body: JSON.stringify({ values: decideForm }),
  })
  const payload = await res.json()
  decideRows.value = payload.items ?? []
}

async function issue(row: Row) {
  const payload = await post(`/circuits/${findCircuitId(row.回路编号)}/issue`, {
    日期: decideForm.date,
    时刻: decideForm.clock,
  })
  notify(payload.message, payload.ok)
  await Promise.all([loadControls(), loadCircuits(), loadSchedules()])
}

// ---- 台账 ----
const circuits = ref<Row[]>([])

async function loadCircuits() {
  circuits.value = (await (await request(`${ENDPOINT}/circuits`)).json()).items
}
function findCircuitId(code: string) {
  return circuits.value.find((item) => item.回路编号 === code)?.id
}
function overLimit(row: Row) {
  return row.当前电流 != null && Number(row.当前电流) > Number(row.电流上限)
}
async function reportCurrent(row: Row) {
  const raw = window.prompt(`上报「${row.回路编号}」当前电流（A），上限 ${row.电流上限} A`, String(row.当前电流 ?? ''))
  if (raw == null) return
  const payload = await post(`/circuits/${row.id}/current`, { 当前电流: raw })
  notify(payload.message, payload.ok)
  await Promise.all([loadCircuits(), loadAlarms()])
}
async function markFault(row: Row) {
  const desc = window.prompt(`将「${row.回路编号}」置为故障，请填写故障描述`, '回路故障，待检修')
  if (desc == null) return
  const payload = await post(`/circuits/${row.id}/status`, { 回路状态: '故障', 故障描述: desc })
  notify(payload.message, payload.ok)
  await Promise.all([loadCircuits(), loadSchedules()])
}
async function repair(row: Row) {
  const payload = await post(`/circuits/${row.id}/status`, { 回路状态: '正常' })
  notify(payload.message, payload.ok)
  await Promise.all([loadCircuits(), loadSchedules()])
}

// ---- 排程 ----
const scheduleDate = ref('2026-09-30')
const schedules = ref<Row[]>([])
const genForm = reactive({ start: '2026-09-25', end: '2026-10-07' })

async function loadSchedules() {
  const query = new URLSearchParams(scheduleDate.value ? { date: scheduleDate.value } : {})
  schedules.value = (await (await request(`${ENDPOINT}/schedules?${query}`)).json()).items
}
async function generateSchedules() {
  const payload = await post('/schedules/generate', genForm)
  notify(payload.message, payload.ok)
  await loadSchedules()
}
function scheduleStatusClass(status: string) {
  if (status === '已下发') return 'on'
  if (status === '不参与排程') return 'off'
  return 'g2'
}

// ---- 控制记录 ----
const controls = ref<Row[]>([])
const controlsOnlyEffective = ref(false)

async function loadControls() {
  controls.value = (await (await request(`${ENDPOINT}/controls?effective=${controlsOnlyEffective.value}`)).json()).items
}

// ---- 告警 ----
const alarms = ref<Row[]>([])

async function loadAlarms() {
  alarms.value = (await (await request(`${ENDPOINT}/alarms`)).json()).items
}
async function resolveAlarm(row: Row) {
  const res = await request(`${ENDPOINT}/alarms/${row.id}/resolve`, { method: 'POST' })
  const payload = await res.json()
  notify(payload.message, payload.ok)
  await loadAlarms()
}

// ---- 判定标准 ----
const parks = ref<Row[]>([])
const parkDraft = reactive<Record<number, number>>({})
const windowRules = ref<Row[]>([])
const festivals = ref<Row[]>([])
const festivalForm = reactive({
  节庆名称: '', 开始日期: '', 结束日期: '', 开灯时间: '18:00', 关灯时间: '23:00', 开灯档位: 3,
})

async function loadRules() {
  parks.value = (await (await request(`${ENDPOINT}/parks`)).json()).items
  parks.value.forEach((park) => { parkDraft[park.id] = park.电流上限 })
  windowRules.value = (await (await request(`${ENDPOINT}/rules/windows`)).json()).items
  festivals.value = (await (await request(`${ENDPOINT}/rules/festivals`)).json()).items
}
async function saveThreshold(park: Row) {
  const payload = await post(`/parks/${park.id}/threshold`, { 电流上限: parkDraft[park.id] })
  notify(payload.message, payload.ok)
  await Promise.all([loadRules(), loadCircuits(), loadAlarms()])
}
async function saveWindow(rule: Row) {
  const payload = await post(`/rules/windows/${rule.id}`, {
    开灯时间: rule.开灯时间, 关灯时间: rule.关灯时间, 开灯档位: rule.开灯档位,
  })
  notify(payload.message, payload.ok)
  await loadSchedules()
}
async function saveFestival() {
  const payload = await post('/rules/festivals', { ...festivalForm })
  notify(payload.message, payload.ok)
  if (payload.ok) {
    Object.assign(festivalForm, { 节庆名称: '', 开始日期: '', 结束日期: '' })
  }
  await Promise.all([loadRules(), loadSchedules()])
}

const stats = ref([
  { label: '正常回路', value: '—' },
  { label: '故障回路（不排程）', value: '—' },
  { label: '电流告警中', value: '—' },
  { label: '今日排程行', value: '—' },
])

async function refreshStats() {
  const monitor = await (await request(`${ENDPOINT}/monitor`)).json()
  const today = (monitor.采集时间 || '').slice(0, 10)
  const todaySchedules = (await (await request(`${ENDPOINT}/schedules?date=${today}`)).json()).items
  stats.value = [
    { label: '正常回路', value: monitor.回路总数 - monitor.故障回路 },
    { label: '故障回路（不排程）', value: monitor.故障回路 },
    { label: '电流告警中', value: monitor.电流告警中 },
    { label: `今日（${today}）排程行`, value: todaySchedules.length },
  ]
}

onMounted(async () => {
  await Promise.all([runDecide(), loadCircuits(), loadSchedules(), loadControls(), loadAlarms(), loadRules()])
  await refreshStats()
})
</script>

<style scoped>
.lt-tabs { display: flex; gap: 6px; margin: 8px 0 12px; flex-wrap: wrap; }
.lt-tab { border: 1px solid var(--border); background: #fff; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
.lt-tab.active { background: var(--brand); color: #fff; border-color: var(--brand); }
.lt-panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.lt-message { font-size: 13px; padding: 8px 10px; border-radius: 6px; margin: 0 0 10px; }
.lt-message.ok { background: #ecfdf3; color: #027a48; border: 1px solid #abefc6; }
.lt-gear { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.lt-gear.on { background: #ecfdf3; color: #027a48; }
.lt-gear.off { background: #fef3f2; color: #b42318; }
.lt-gear.g1 { background: #eff8ff; color: #175cd3; }
.lt-gear.g2 { background: #fffaeb; color: #b54708; }
.lt-gear.g3 { background: #fdf4ff; color: #c11574; }
.lt-reason { color: var(--muted); font-size: 12px; max-width: 320px; }
.lt-sub { color: var(--muted); font-size: 12px; margin-top: 2px; }
.lt-h3 { font-size: 14px; margin: 18px 0 8px; }
.lt-check { display: flex; align-items: center; gap: 6px; }
.lt-check input { width: auto; }
.data-table input, .data-table select { width: 100%; min-width: 90px; padding: 4px 6px; border: 1px solid var(--border); border-radius: 4px; }
.link:disabled { color: #98a2b3; cursor: not-allowed; }
</style>
