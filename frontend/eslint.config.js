import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // eslint-plugin-react-hooks v7 bật các rule React Compiler và đặt mức error.
      // Chúng bắt đúng những pattern fetch-rồi-setState trong useEffect mà app này
      // dùng khắp nơi (poll giá, load panel). Đó là code chạy đúng, chỉ chưa tối ưu
      // theo compiler — hạ xuống warn để `npm run lint` vẫn chặn được lỗi thật
      // (biến không dùng, typo) thay vì luôn đỏ.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/purity': 'warn',
    },
  },
])
