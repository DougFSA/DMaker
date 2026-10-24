import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['node_modules/**', '../src/dmaker/ui/dist/**', 'dist/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // só as regras de correção do Vue; o estilo de quebra de linha dos templates não é policiado
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue', '**/*.ts'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { parser: tseslint.parser },
    },
    rules: {
      'vue/no-v-html': 'error',
      'vue/block-order': ['error', { order: ['script', 'template', 'style'] }],
      // o texto de tela é PT-BR e as props seguem a API do backend (snake_case) nos tipos, não nos componentes
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
)
