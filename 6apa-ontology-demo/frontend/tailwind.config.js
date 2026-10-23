/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: '#0a111d', panel: '#101a2b', panel2: '#16233a', raised: '#1c2c46' },
        line: { DEFAULT: '#23344f', soft: '#1a2940' },
        fg: { DEFAULT: '#dde7f7', dim: '#9fb0cc', mute: '#6f819e' },
        brand: '#35c4d7',
        ok: '#3fcf8e', warn: '#f2c744', err: '#f2557a', info: '#4c8dff',
        equip: '#ff9f45', part: '#b07cff', prop: '#3fcf8e', tagc: '#f2c744', unmatched: '#6b7a90'
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', '-apple-system', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'Menlo', 'monospace']
      }
    }
  },
  plugins: []
}
