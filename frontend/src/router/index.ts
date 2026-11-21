import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import ReworkWorkbench from '@/views/ReworkWorkbench.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/quality_rework', name: 'quality_rework', component: ReworkWorkbench },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
