/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        // 工业软件深色底：低饱和、高对比、长时间盯屏不刺眼
        ink: { 900: '#0b0f14', 800: '#111823', 700: '#18202c', 600: '#212b39', 500: '#2c3848' },
        line: '#2a3647',
        accent: { DEFAULT: '#38bdf8', dim: '#0ea5e9' },
        ok: '#34d399',
        warn: '#fbbf24',
        bad: '#f87171',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
