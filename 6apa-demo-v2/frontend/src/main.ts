import { createApp } from 'vue'
import App from './App.vue'
import { initStatic } from './api/static'
import './style.css'

// 单文件版：页面里内嵌了数据快照时，先解出数据再挂载
initStatic()
  .catch((e) => {
    const app = document.getElementById('app')
    if (app) app.innerHTML = `<div class="empty m-6">单文件版数据加载失败：${String(e)}。请使用新版 Chrome / Edge 打开。</div>`
    throw e
  })
  .then(() => createApp(App).mount('#app'))
