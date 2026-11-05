/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        // 浅色主题：ink = 页面底色，panel = 卡片，panel2 = 表头 / 次级底色
        ink: { DEFAULT: '#f4f6f9', panel: '#ffffff', panel2: '#f1f4f8', raised: '#e8edf3' },
        line: { DEFAULT: '#d6dde7', soft: '#e6ebf1' },
        fg: { DEFAULT: '#1f2937', dim: '#4b5563', mute: '#8391a2' },
        brand: '#0e8fa3',
        ok: '#15803d', warn: '#b45309', err: '#dc2626', info: '#2563eb',
        equip: '#ea7a1a', part: '#8b5cf6', prop: '#15803d', tagc: '#b45309', unmatched: '#94a3b8'
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', '-apple-system', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'Menlo', 'monospace']
      }
    }
  },
  plugins: []
}
