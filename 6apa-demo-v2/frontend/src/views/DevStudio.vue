<script setup lang="ts">
/**
 * 开发态（需求 4.2）：元模型、层级类型、类库（类树 + 类详情各模板）、关系类型、映射规则、算法库。
 * 本 Demo 的类库由 105 车间实例归纳得到，只读；开发态修改触发工程态更新的联动不做。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { openInEngineering } from '@/composables/useNav'
import GlobalSections from './GlobalSections.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const SECTIONS = [['class', '类库'], ['meta', '元模型'], ['hier', '层级类型'], ['rel', '关系类型'], ['map', '映射规则'], ['algo', '算法库']] as const
const section = ref<string>('class')
const tree = ref<Any>(null)
const open = ref<Record<string, boolean>>({ 'meta:设备': true })
const classId = ref('')
const cls = ref<Any>(null)
const clsTab = ref('base')
const kw = ref('')
const meta = ref<Any>(null)
const hier = ref<Any>(null)
const rels = ref<Any>(null)
const maps = ref<Any>(null)
const tagIn = ref('TI_1301C')
const parsed = ref<Any>(null)
const err = ref('')

async function loadSection(): Promise<void> {
  err.value = ''
  try {
    if (section.value === 'class' && !tree.value) tree.value = await api.devClassTree()
    if (section.value === 'meta' && !meta.value) meta.value = await api.devMetamodel()
    if (section.value === 'hier' && !hier.value) hier.value = await api.devHierarchyTypes()
    if (section.value === 'rel' && !rels.value) rels.value = await api.devRelationTypes()
    if (section.value === 'map' && !maps.value) maps.value = await api.devMappingRules()
  } catch (e) { err.value = String((e as Error).message) }
}
watch(section, loadSection, { immediate: true })
watch(classId, async (id) => {
  if (!id) return
  cls.value = null
  try { cls.value = await api.devClass(id) } catch (e) { err.value = String((e as Error).message) }
  clsTab.value = 'base'
})
const filtered = computed(() => {
  const root = tree.value?.items?.[0]
  if (!root || !kw.value) return root
  const k = kw.value
  const cats = root.children.map((c: Any) => ({ ...c, children: c.children.filter((t: Any) => t.label.includes(k) || t.code.includes(k)) }))
    .filter((c: Any) => c.children.length || c.label.includes(k))
  return { ...root, children: cats }
})
async function parse(): Promise<void> {
  parsed.value = null
  try { parsed.value = await api.devParseTag(tagIn.value) } catch (e) { err.value = String((e as Error).message) }
}
const CLS_TABS = [['base', '基本信息'], ['attrs', '类属性'], ['params', '参数模板'], ['cons', '约束模板'], ['phen', '现象 / 工况模板'],
  ['cause', '根因模板'], ['infl', '工艺影响模板'], ['caps', '挂载能力'], ['inst', '实例清单']] as const
const tabCount = (k: string): number | undefined => {
  const c = cls.value
  if (!c || c.abstract) return undefined
  return ({ attrs: c.attributes.length, params: c.parameters.length, cons: c.constraints.length, phen: c.phenomena.length,
            cause: c.causes.length, infl: c.influences.length, caps: c.capabilities.length, inst: c.instances.length } as Record<string, number>)[k]
}
</script>

<template>
  <div class="h-full grid grid-cols-[300px_1fr] min-h-0">
    <aside class="border-r border-line bg-ink-panel flex flex-col min-h-0">
      <div class="px-3 py-2 border-b border-line">
        <div class="text-xs text-fg-mute mb-1.5">开发态 · 类库 {{ tree?.version?.version ?? 'v0.1' }}（{{ tree?.version?.status ?? '草案' }}）</div>
        <div class="flex flex-wrap gap-1">
          <button v-for="[k, l] in SECTIONS" :key="k" class="ctl !py-0.5" :class="{ 'ctl-on': section === k }" @click="section = k">{{ l }}</button>
        </div>
      </div>
      <template v-if="section === 'class'">
        <div class="px-3 py-2"><input v-model="kw" class="inp w-full" placeholder="按类名 / 编码筛选" /></div>
        <div class="flex-1 overflow-auto px-1 pb-3 text-[13px]">
          <template v-if="filtered">
            <div class="tree-row" :class="{ 'tree-row-on': classId === filtered.id }" @click="classId = filtered.id">
              <span class="text-fg-mute w-3">▾</span><span class="pill pill-info !py-0">元类</span><span class="flex-1">{{ filtered.label }}</span>
              <span class="text-[10.5px] text-fg-mute">{{ filtered.equipment }}</span>
            </div>
            <template v-for="c in filtered.children" :key="c.id">
              <div class="tree-row pl-5" :class="{ 'tree-row-on': classId === c.id }" @click="classId = c.id; open[c.id] = !open[c.id] || kw !== ''">
                <span class="text-fg-mute w-3">{{ open[c.id] || kw ? '▾' : '▸' }}</span><span class="flex-1 italic">{{ c.label }}</span>
                <span class="text-[10.5px] text-fg-mute">{{ c.children.length }} 类</span>
              </div>
              <template v-if="open[c.id] || kw">
                <div v-for="t in c.children" :key="t.id" class="tree-row pl-10" :class="{ 'tree-row-on': classId === t.id }" @click="classId = t.id">
                  <span class="flex-1 truncate">{{ t.label }}</span>
                  <span class="text-[10.5px] text-fg-mute tabular-nums" title="直接实例：设备组 / 设备">{{ t.groups }} / {{ t.equipment }}</span>
                </div>
              </template>
            </template>
          </template>
          <div v-else class="px-3 text-fg-mute text-xs">加载中…</div>
        </div>
        <div class="px-3 py-2 border-t border-line text-[11px] text-fg-mute">斜体 = 抽象类（资产大类）；数字 = 实例数（设备组 / 设备）</div>
      </template>
      <div v-else class="flex-1 p-3 text-xs text-fg-mute leading-relaxed">
        <template v-if="section === 'meta'">元模型定义本体中允许存在的元类（对象种类）。预置元类不可删除；扩展元类（如能源计量点、组织单元）在没有类和实例引用时可删除。</template>
        <template v-else-if="section === 'hier'">层级类型决定空间层级的级数与名称；105 车间使用「车间—工艺段—工序」模板。</template>
        <template v-else-if="section === 'rel'">所有关系都属于一个关系类型；关系类型是全局图谱视角、TTL 导出和一致性校验的依据（需求附录 B）。</template>
        <template v-else-if="section === 'map'">映射规则把位号、设备编号等外部数据转换为本体实例与关系，是快速构建的核心配置。可在右侧输入样例测试。</template>
        <template v-else>算法库只登记调用契约，算法由算法服务提供。</template>
      </div>
    </aside>

    <main class="min-h-0 overflow-auto px-5 py-4 text-sm">
      <div v-if="err" class="empty mb-3">{{ err }}</div>

      <!-- 类库 -->
      <template v-if="section === 'class'">
        <div v-if="!classId" class="empty">左侧选择一个类查看定义（属性、参数模板、约束 / 现象 / 根因 / 工艺影响模板、挂载能力、实例清单）</div>
        <div v-else-if="!cls" class="text-fg-mute">加载中…</div>
        <template v-else>
          <div class="flex items-center gap-2 mb-1">
            <h2 class="text-[17px] font-semibold">{{ cls.name }}</h2>
            <span class="pill pill-plain font-mono">{{ cls.code }}</span>
            <span class="pill" :class="cls.abstract ? 'pill-mute' : 'pill-info'">{{ cls.abstract ? '抽象类' : '类' }}</span>
            <span class="pill pill-warn">{{ cls.status ?? '草案·待工艺确认' }}</span>
            <span class="text-xs text-fg-mute">元类 {{ cls.metaclass }}<template v-if="cls.parent"> · 父类 {{ cls.parent }}</template></span>
          </div>
          <div class="text-xs text-fg-mute mb-3">{{ cls.note }}</div>
          <template v-if="cls.abstract">
            <table class="tbl"><thead><tr><th>子类</th><th>设备组</th><th>设备</th></tr></thead><tbody>
              <tr v-for="s in cls.subclasses" :key="s.id" @click="classId = s.id"><td class="text-brand">{{ s.name }}</td><td>{{ s.groups }}</td><td>{{ s.equipment }}</td></tr>
            </tbody></table>
          </template>
          <template v-else>
            <div class="flex flex-wrap gap-1.5 mb-3">
              <button v-for="[k, l] in CLS_TABS" :key="k" class="asset-tab" :class="{ 'asset-tab-on': clsTab === k }" @click="clsTab = k">
                {{ l }}<span v-if="tabCount(k)" class="asset-tab-count">{{ tabCount(k) }}</span>
              </button>
            </div>
            <dl v-if="clsTab === 'base'" class="kv card">
              <dt>类编码</dt><dd class="font-mono">{{ cls.code }}</dd><dt>类名称</dt><dd>{{ cls.name }}</dd>
              <dt>所属元类</dt><dd>{{ cls.metaclass }}</dd><dt>父类</dt><dd>{{ cls.parent }}（抽象）</dd>
              <dt>状态</dt><dd>{{ cls.status }}</dd><dt>类库版本</dt><dd>{{ cls.libraryVersion }}</dd>
              <dt>实例</dt><dd>{{ cls.counts.groups }} 个设备组 · {{ cls.counts.equipment }} 台设备</dd>
              <dt>可见页签</dt><dd>{{ cls.visibleTabs.join('、') }}</dd>
            </dl>
            <table v-else-if="clsTab === 'attrs'" class="tbl"><thead><tr><th>属性</th><th>类型 / 单位</th><th>来源</th><th>说明</th></tr></thead><tbody>
              <tr v-for="a in cls.attributes" :key="a.name" class="!cursor-default"><td>{{ a.name }}</td><td class="text-fg-dim">{{ a.type }}</td>
                <td><span class="pill" :class="a.from.startsWith('本类') ? 'pill-info' : 'pill-plain'">{{ a.from.startsWith('本类') ? '本类' : '继承' }}</span> <span class="text-[11px] text-fg-mute">{{ a.from }}</span></td>
                <td class="text-xs text-fg-mute">{{ a.note }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'params'" class="tbl"><thead><tr><th>参数模板</th><th>参数类别</th><th>类型 · 单位</th><th>必备</th><th>覆盖设备组</th><th>位号匹配模式（样例）</th></tr></thead><tbody>
              <tr v-for="p in cls.parameters" :key="p.name" class="!cursor-default">
                <td>{{ p.name }}<span v-if="p.semantic" class="pill pill-ok !py-0 ml-1">工艺属性</span></td><td>{{ p.category }}</td><td class="text-fg-dim">{{ p.valueType }}</td>
                <td>{{ p.required ? '是' : '' }}</td><td class="tabular-nums">{{ p.groups }} / {{ cls.counts.groups }}</td>
                <td class="font-mono text-xs">{{ p.tagRule }}<span v-if="p.tagExamples.length" class="text-fg-mute font-sans">（如 {{ p.tagExamples.join('、') }}）</span></td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'cons'" class="tbl"><thead><tr><th>编号</th><th>适用参数模板</th><th>适用工况</th><th>LL / L / 正常下 / 正常上 / H / HH</th><th>单位</th><th>限值来源</th><th>状态</th></tr></thead><tbody>
              <tr v-for="c in cls.constraints" :key="c.id" class="!cursor-default"><td class="font-mono">{{ c.id }}</td><td>{{ c.parameter }}</td><td>{{ c.mode }}</td>
                <td class="font-mono text-xs">{{ c.values }}</td><td>{{ c.unit }}</td><td class="text-xs text-fg-mute">{{ c.source }}</td><td class="text-xs">{{ c.status }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'phen'" class="tbl"><thead><tr><th>现象 / 工况模板</th><th>类别</th><th>严重</th><th>判定规则模板（本对象.参数模板）</th><th>覆盖设备组</th></tr></thead><tbody>
              <tr v-for="p in cls.phenomena" :key="p.name" class="!cursor-default"><td>{{ p.name }}</td><td>{{ p.category }}</td><td>{{ p.severity }}</td>
                <td class="text-xs font-mono">{{ p.ruleText }}</td><td class="tabular-nums">{{ p.groups }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'cause'" class="tbl"><thead><tr><th>原因现象模板</th><th></th><th>结果现象模板</th><th>适用范围</th><th>默认置信度</th><th>机理</th></tr></thead><tbody>
              <tr v-for="(c, i) in cls.causes" :key="i" class="!cursor-default"><td>{{ c.cause }}</td><td class="text-brand">导致</td><td>{{ c.effect }}</td>
                <td class="text-xs" :class="c.scope === '类内' ? '' : 'text-info'">{{ c.scope }}</td><td>{{ c.confidence }}</td><td class="text-xs text-fg-dim">{{ c.mechanism }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'infl'" class="tbl"><thead><tr><th>来源参数</th><th>方向</th><th>目标参数</th><th>机理</th></tr></thead><tbody>
              <tr v-for="(r, i) in cls.influences" :key="i" class="!cursor-default"><td>{{ r.from }}</td>
                <td :class="r.direction === '负向影响' ? 'text-warn' : 'text-ok'">{{ r.direction }}</td><td>{{ r.to }}</td><td class="text-xs text-fg-dim">{{ r.mechanism }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'caps'" class="tbl"><thead><tr><th>编码</th><th>能力</th><th>类型</th><th>说明</th><th>提供方</th></tr></thead><tbody>
              <tr v-for="c in cls.capabilities" :key="c.id" class="!cursor-default"><td class="font-mono text-xs">{{ c.id }}</td><td>{{ c.name }}</td><td class="text-xs">{{ c.type }}</td>
                <td class="text-xs text-fg-dim">{{ c.description }}</td><td class="text-xs text-fg-mute">{{ c.provider }}</td></tr>
            </tbody></table>
            <table v-else-if="clsTab === 'inst'" class="tbl"><thead><tr><th>实例（设备组）</th><th>成员设备</th><th>导航</th><th></th></tr></thead><tbody>
              <tr v-for="x in cls.instances" :key="x.id" class="!cursor-default"><td>{{ x.name }}</td><td>{{ x.members }}</td><td class="text-xs">{{ x.inNav ? '在导航中' : '未纳入导航' }}</td>
                <td><button v-if="x.inNav && !staticBackend" class="ctl" @click="openInEngineering(x.id, x.opId, x.segmentId)">在工程态打开 ↗</button></td></tr>
            </tbody></table>
            <div class="text-[11px] text-fg-mute mt-2">模板由实例归纳，只读；需求中的类定义、参数模板编辑、类库版本对比与发布在正式产品中实现。</div>
          </template>
        </template>
      </template>

      <!-- 元模型 -->
      <template v-else-if="section === 'meta'">
        <h2 class="text-[16px] font-semibold mb-2">元模型 · 元类</h2>
        <table v-if="meta" class="tbl"><thead><tr><th>编码</th><th>元类</th><th>Demo 中对应</th><th>实例数</th><th>说明</th><th>预置</th></tr></thead><tbody>
          <tr v-for="m in meta.items" :key="m.code" class="!cursor-default"><td class="font-mono text-xs">{{ m.code }}</td><td class="font-medium">{{ m.name }}</td>
            <td class="text-fg-dim">{{ m.demo }}</td><td class="tabular-nums">{{ m.instances }}</td><td class="text-xs text-fg-mute">{{ m.note }}</td>
            <td><span class="pill" :class="m.preset ? 'pill-plain' : 'pill-mute'">{{ m.preset ? '预置' : '扩展' }}</span></td></tr>
        </tbody></table>
      </template>

      <!-- 层级类型 -->
      <template v-else-if="section === 'hier'">
        <h2 class="text-[16px] font-semibold mb-2">层级类型与层级模板</h2>
        <div v-for="t in hier?.templates ?? []" :key="t.name" class="card mb-3">
          <div class="sec-title">{{ t.name }}</div>
          <table class="tbl"><thead><tr><th>编码</th><th>层级类型</th><th>允许上级</th><th>允许下级</th><th>可绑定图纸</th><th>首页卡片</th><th>节点数</th></tr></thead><tbody>
            <tr v-for="l in t.levels" :key="l.code" class="!cursor-default"><td class="font-mono text-xs">{{ l.code }}</td><td class="font-medium">{{ l.name }}</td><td>{{ l.parent }}</td><td>{{ l.child }}</td>
              <td>{{ l.drawing ? '是' : '' }}</td><td>{{ l.card ? '是' : '' }}</td><td class="tabular-nums">{{ l.count ?? '—' }}</td></tr>
          </tbody></table>
          <div class="text-[11px] text-fg-mute mt-1">{{ t.note }}</div>
        </div>
      </template>

      <!-- 关系类型 -->
      <template v-else-if="section === 'rel'">
        <h2 class="text-[16px] font-semibold mb-2">关系类型（预置，需求附录 B）</h2>
        <table v-if="rels" class="tbl"><thead><tr><th>编码</th><th>关系类型</th><th>反向名称</th><th>源端</th><th>目标端</th><th>方向</th><th>图谱视角</th><th>TTL 谓词</th><th>附加属性 / 说明</th><th>实例数</th></tr></thead><tbody>
          <tr v-for="r in rels.items" :key="r.code" class="!cursor-default"><td class="font-mono text-xs">{{ r.code }}</td><td class="font-medium whitespace-nowrap">{{ r.name }}</td><td class="text-fg-dim">{{ r.inverse }}</td>
            <td class="text-xs">{{ r.from }}</td><td class="text-xs">{{ r.to }}</td><td class="text-xs">{{ r.direction }}</td><td class="text-xs">{{ r.views }}</td>
            <td class="font-mono text-[11px]">{{ r.ttl }}</td><td class="text-xs text-fg-mute">{{ r.attrs }}</td><td class="tabular-nums">{{ r.count }}</td></tr>
        </tbody></table>
        <div class="text-[11px] text-fg-mute mt-2">{{ rels?.note }}</div>
      </template>

      <!-- 映射规则 -->
      <template v-else-if="section === 'map'">
        <h2 class="text-[16px] font-semibold mb-2">映射规则 · 位号解析</h2>
        <table v-if="maps" class="tbl mb-3"><thead><tr><th>编码</th><th>优先级</th><th>规则</th><th>匹配表达式</th><th>输出</th><th>置信度</th><th>命中位号</th></tr></thead><tbody>
          <tr v-for="r in maps.items" :key="r.code" class="!cursor-default"><td class="font-mono text-xs">{{ r.code }}</td><td>{{ r.priority }}</td><td>{{ r.name }}</td>
            <td class="font-mono text-[11px] max-w-[320px] break-all">{{ r.pattern }}</td><td class="text-xs">{{ r.target }}</td><td>{{ r.confidence }}</td>
            <td class="tabular-nums">{{ r.hits }} / {{ maps.total }}</td></tr>
        </tbody></table>
        <div class="card space-y-2">
          <div class="sec-title">规则测试</div>
          <div class="flex items-center gap-2">
            <input v-model="tagIn" class="inp w-60 font-mono" placeholder="输入位号，如 TI_1301C" @keydown.enter="parse" />
            <button class="btn btn-primary" :disabled="!!staticBackend" @click="parse">测试</button>
            <span class="text-xs text-fg-mute">样例：</span>
            <button v-for="e in maps?.examples ?? []" :key="e" class="ctl font-mono !py-0" @click="tagIn = e; parse()">{{ e }}</button>
          </div>
          <div v-if="staticBackend" class="text-xs text-fg-mute">单文件版不支持规则测试</div>
          <div v-if="parsed" class="grid grid-cols-2 gap-3 text-xs">
            <div>
              <div class="font-medium mb-1">命中规则：{{ parsed.rule ? `${parsed.rule.code} ${parsed.rule.name}（置信度 ${parsed.rule.confidence}）` : '无' }}</div>
              <table class="tbl"><tbody><tr v-for="f in parsed.fields" :key="f.name" class="!cursor-default"><td class="text-fg-mute w-28">{{ f.name }}</td><td class="font-mono">{{ f.value }}</td><td class="text-fg-dim">{{ f.meaning }}</td></tr></tbody></table>
              <div v-if="parsed.rule" class="mt-1 text-fg-dim">输出：{{ parsed.rule.target }}</div>
            </div>
            <div>
              <div class="font-medium mb-1">点表中（位号目录）</div>
              <dl v-if="parsed.catalog" class="kv">
                <dt>点描述</dt><dd>{{ parsed.catalog.description }}</dd><dt>设备</dt><dd>{{ parsed.catalog.equipment }}</dd>
                <dt>块类型 / 变量类别</dt><dd>{{ parsed.catalog.blockType }} · {{ parsed.catalog.variableCategory }}</dd>
                <dt>单位</dt><dd>{{ parsed.catalog.unit }}</dd><dt>归属</dt><dd>置信度 {{ parsed.catalog.confidence }} · {{ parsed.catalog.basis }}</dd>
              </dl>
              <div v-else class="text-fg-mute">点表中没有这个位号</div>
            </div>
          </div>
        </div>
        <div class="text-[11px] text-fg-mute mt-2">{{ maps?.note }}</div>
      </template>

      <GlobalSections v-else-if="section === 'algo'" kind="global:algo" />
    </main>
  </div>
</template>
