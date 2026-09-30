<template>
  <section class="page" data-module="lighting-monitor">
    <header class="page-head">
      <div>
        <h2>亮灯监控</h2>
        <p class="page-desc">本页只读取监控接口：各回路档位与「景观照明开关口径」页的控制记录是同一份数据，不做二次推算。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/lighting">返回开关口径管理</RouterLink>
        <button class="btn primary" type="button" @click="reload">刷新监控</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card"><span class="stat-label">采集时间</span><strong class="stat-value small">{{ monitor.采集时间 ?? '—' }}</strong></article>
      <article class="stat-card"><span class="stat-label">回路总数</span><strong class="stat-value">{{ monitor.回路总数 ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">故障回路</span><strong class="stat-value warn">{{ monitor.故障回路 ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">电流告警中</span><strong class="stat-value warn">{{ monitor.电流告警中 ?? 0 }}</strong></article>
      <article class="stat-card"><span class="stat-label">台账-控制记录一致</span><strong class="stat-value" :class="consistency.ok ? 'ok' : 'warn'">{{ consistency.ok ? '一致' : '不一致' }}</strong></article>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>回路编号</th><th>回路名称</th><th>园区</th><th>回路状态</th>
          <th>电流(A) / 上限</th><th>当前档位（取控制记录）</th><th>档位依据</th><th>电流告警</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in monitor.items ?? []" :key="row.id">
          <td>{{ row.回路编号 }}</td>
          <td>{{ row.回路名称 }}</td>
          <td>{{ row.园区 }}</td>
          <td>
            <span :class="row.回路状态 === '故障' ? 'lt-gear off' : 'lt-gear on'">{{ row.回路状态 }}</span>
          </td>
          <td :class="row.电流告警 ? 'error-text' : ''">
            {{ row.当前电流 ?? '—' }} / {{ row.电流上限 }}
          </td>
          <td><span class="lt-gear" :class="`g${row.当前档位}`">{{ row.档位结论 }}</span></td>
          <td class="lt-reason">{{ row.档位依据 }}</td>
          <td>
            <span v-if="row.电流告警" class="lt-gear off">告警中</span>
            <span v-else class="lt-gear on">正常</span>
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>数据来源：GET /api/lighting/monitor（档位口径与控制记录、照明台账一致）</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const monitor = ref<{ items?: Row[] } & Record<string, any>>({})
const consistency = ref<Record<string, any>>({ ok: true })

async function reload() {
  const [mon, check] = await Promise.all([
    request('/api/lighting/monitor').then((res) => res.json()),
    request('/api/lighting/consistency').then((res) => res.json()),
  ])
  monitor.value = mon
  consistency.value = check
}

onMounted(reload)
</script>

<style scoped>
.lt-gear { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.lt-gear.on { background: #ecfdf3; color: #027a48; }
.lt-gear.off { background: #fef3f2; color: #b42318; }
.lt-gear.g1 { background: #eff8ff; color: #175cd3; }
.lt-gear.g2 { background: #fffaeb; color: #b54708; }
.lt-gear.g3 { background: #fdf4ff; color: #c11574; }
.lt-reason { color: var(--muted); font-size: 12px; max-width: 360px; }
.stat-value.small { font-size: 14px; }
.stat-value.warn { color: #b42318; }
.stat-value.ok { color: #027a48; }
</style>
