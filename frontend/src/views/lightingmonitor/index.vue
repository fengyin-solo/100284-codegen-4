<template>
  <section class="page lighting-monitor" data-module="lighting-monitor">
    <header class="page-head">
      <div>
        <h2>景观照明实时监控</h2>
        <p class="page-desc">
          本页为只读监控视图：当前档位与「景观照明调度台」取同一份接口数据——口径快照读 /lighting/snapshot，
          回路档位直接读控制记录（/lighting/controls 同源结论），不另算一套，保证两个页面结论一致。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="loadAll">刷新</button>
      </div>
    </header>

    <div class="snapshot-bar" :class="snapshot['允许开灯'] ? 'is-on' : 'is-off'">
      <div class="snapshot-main">
        <strong>{{ snapshot['当前时间'] || '—' }}</strong>
        <span>节气季节：{{ snapshot['节气季节'] || '—' }}</span>
        <span class="snapshot-verdict">
          口径结论：
          <em>{{ snapshot['允许开灯'] ? `允许开灯 · ${snapshot['口径档位名称']}（${snapshot['口径档位']}档）` : '不允许开灯' }}</em>
        </span>
        <span class="snapshot-source">依据：{{ snapshot['判定依据'] || '—' }}</span>
      </div>
      <div class="snapshot-meta">
        <span>口径版本 v{{ snapshot['口径版本'] || 1 }}（与调度台同版本）</span>
        <span>最近重算：{{ snapshot['最近重算'] || '—' }}</span>
      </div>
    </div>
    <p class="verdict-reason">{{ snapshot['判定说明'] }}</p>

    <div class="stat-row">
      <article class="stat-card"><span class="stat-label">监控回路</span><strong class="stat-value">{{ ledger.length }}</strong></article>
      <article class="stat-card"><span class="stat-label">故障停用</span><strong class="stat-value">{{ faultCount }}</strong></article>
      <article class="stat-card"><span class="stat-label">电流超限</span><strong class="stat-value" :class="overCount ? 'alarm' : ''">{{ overCount }}</strong></article>
      <article class="stat-card"><span class="stat-label">未处理电流告警</span><strong class="stat-value" :class="openAlarms ? 'alarm' : ''">{{ openAlarms }}</strong></article>
      <article class="stat-card"><span class="stat-label">台账/控制记录核对</span>
        <strong class="stat-value" :class="consistency['一致'] ? 'ok' : 'alarm'">{{ consistency['一致'] ? '一致' : '不一致' }}</strong>
      </article>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>回路编号</th><th>回路名称</th><th>园区</th><th>回路状态</th>
          <th>当前电流A</th><th>园区上限A</th><th>当前档位（同控制记录）</th><th>档位来源</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in ledger" :key="row['回路编号']" :class="{ 'row-fault': row['回路状态'] === '故障', 'row-over': row['电流是否超限'] }">
          <td>{{ row['回路编号'] }}</td>
          <td>{{ row['回路名称'] }}</td>
          <td>{{ row['园区'] }}</td>
          <td>{{ row['回路状态'] }}</td>
          <td :class="row['电流是否超限'] ? 'alarm' : ''">{{ fmt(row['当前电流A']) }}</td>
          <td>{{ fmt(row['电流上限A']) }}</td>
          <td>
            <span class="lamp-dot" :class="`dot-${row['当前档位']}`"></span>
            {{ row['当前档位名称'] }}（{{ row['当前档位'] }}档）
          </td>
          <td class="muted-cell">{{ row['档位来源'] }}</td>
        </tr>
      </tbody>
    </table>

    <h3>最新控制记录（档位的唯一数据源）</h3>
    <table class="data-table">
      <thead>
        <tr><th>记录#</th><th>回路编号</th><th>时段日期</th><th>下发时间</th><th>生效档位</th><th>判定依据</th><th>状态</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in latestControls" :key="row.id">
          <td>{{ row.id }}</td>
          <td>{{ row['回路编号'] }}</td>
          <td>{{ row['时段日期'] }}</td>
          <td>{{ row['下发时间'] }}</td>
          <td>{{ row['档位名称'] }}（{{ row['档位'] }}档）</td>
          <td class="muted-cell">{{ row['判定依据'] }}</td>
          <td>{{ row['状态'] }}</td>
        </tr>
        <tr v-if="!latestControls.length"><td colspan="7" class="empty-state">暂无已生效控制记录</td></tr>
      </tbody>
    </table>

    <h3>未处理电流告警</h3>
    <table class="data-table">
      <thead><tr><th>告警编号</th><th>园区</th><th>回路编号</th><th>当前电流A</th><th>阈值A</th><th>告警时间</th><th>触发原因</th></tr></thead>
      <tbody>
        <tr v-for="a in openAlarmRows" :key="a.id" class="row-over">
          <td>{{ a['告警编号'] }}</td><td>{{ a['园区'] }}</td><td>{{ a['回路编号'] }}</td>
          <td class="alarm">{{ fmt(a['当前电流A']) }}</td><td>{{ fmt(a['阈值A']) }}</td>
          <td>{{ a['告警时间'] }}</td><td class="muted-cell">{{ a['触发原因'] }}</td>
        </tr>
        <tr v-if="!openAlarmRows.length"><td colspan="7" class="empty-state">暂无未处理告警</td></tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>只读页面，开关灯操作请在「景观照明调度台」执行</span>
      <span>核对版本 v{{ consistency['口径版本'] || 1 }} · {{ consistency['核对时间'] || '—' }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Row = Record<string, any>

const snapshot = ref<Row>({})
const ledger = ref<Row[]>([])
const controls = ref<Row[]>([])
const alarms = ref<Row[]>([])
const consistency = ref<Row>({})

const faultCount = computed(() => ledger.value.filter((r) => r['回路状态'] === '故障').length)
const overCount = computed(() => ledger.value.filter((r) => r['电流是否超限']).length)
const openAlarmRows = computed(() => alarms.value.filter((a) => a['状态'] === '未处理'))
const openAlarms = computed(() => openAlarmRows.value.length)
// 每条回路只展示最新一条控制记录——与台账「当前档位」是同一行数据。
const latestControls = computed(() => {
  const map = new Map<string, Row>()
  for (const record of controls.value) map.set(String(record['回路编号']), record)
  return [...map.values()]
})

function fmt(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toFixed(1)
}

async function loadAll() {
  const [snap, led, ctl, alm, chk] = await Promise.all([
    fetchJson<Row>('/api/lighting/snapshot'),
    fetchJson<{ items: Row[] }>('/api/lighting/ledger'),
    fetchJson<{ items: Row[] }>('/api/lighting/controls'),
    fetchJson<{ items: Row[] }>('/api/lighting/alarms'),
    fetchJson<Row>('/api/lighting/consistency'),
  ])
  snapshot.value = snap
  ledger.value = led.items
  controls.value = ctl.items
  alarms.value = alm.items
  consistency.value = chk
}

onMounted(loadAll)
</script>

<style scoped>
.snapshot-bar { display: flex; justify-content: space-between; gap: 12px; border: 1px solid var(--border); border-left-width: 4px; border-radius: 8px; background: #fff; padding: 10px 14px; flex-wrap: wrap; }
.snapshot-bar.is-on { border-left-color: #15803d; }
.snapshot-bar.is-off { border-left-color: #b42318; }
.snapshot-main { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; font-size: 13px; }
.snapshot-main strong { font-size: 16px; }
.snapshot-verdict em { font-style: normal; color: #15803d; font-weight: 600; }
.is-off .snapshot-verdict em { color: #b42318; }
.snapshot-meta { display: flex; flex-direction: column; font-size: 12px; color: var(--muted); text-align: right; }
.verdict-reason { font-size: 12px; color: var(--muted); margin: 6px 2px 0; }
.muted-cell { color: var(--muted); font-size: 12px; }
.row-over { background: #fff5f5; }
.row-fault { background: #f8fafc; color: var(--muted); }
.alarm { color: #b42318; font-weight: 600; }
.ok { color: #15803d; }
h3 { font-size: 14px; margin: 18px 0 8px; }
.lamp-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; background: #94a3b8; }
.dot-1 { background: #ca8a04; }
.dot-2 { background: #1f6feb; }
.dot-3 { background: #c026d3; box-shadow: 0 0 4px #c026d3; }
</style>
