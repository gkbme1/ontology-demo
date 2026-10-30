import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'assets', component: () => import('@/views/AssetOntology.vue'), meta: { fullWidth: true } },
  { path: '/overview', name: 'overview', component: () => import('@/views/Overview.vue') },
  { path: '/areas', name: 'areas', component: () => import('@/views/ProcessArea.vue') },
  { path: '/areas/:areaId', name: 'area', component: () => import('@/views/ProcessArea.vue'), props: true },
  { path: '/equipment/:equipmentId', name: 'equipment', component: () => import('@/views/Equipment.vue'), props: true },
  { path: '/parameters/:parameterId', name: 'parameter', component: () => import('@/views/Parameter.vue'), props: true },
  { path: '/graph', name: 'graph', component: () => import('@/views/RelationGraph.vue') },
  { path: '/graph/:entityId', name: 'entity', component: () => import('@/views/RelationGraph.vue'), props: true },
  { path: '/relations', name: 'relations', component: () => import('@/views/Relations.vue') },
  { path: '/ontology/:categoryKey', name: 'category', component: () => import('@/views/Ontology.vue'), props: true },
  { path: '/rules', name: 'rules', component: () => import('@/views/Rules.vue') },
  { path: '/data-sources', name: 'sources', component: () => import('@/views/DataSource.vue') },
  { path: '/data-quality', name: 'quality', component: () => import('@/views/DataQuality.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})
