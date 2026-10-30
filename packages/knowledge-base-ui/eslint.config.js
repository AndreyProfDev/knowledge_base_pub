import eslintReact from '@eslint-react/eslint-plugin';
import pluginQuery from '@tanstack/eslint-plugin-query';
import pluginRouter from '@tanstack/eslint-plugin-router';
import { defineConfig, globalIgnores } from 'eslint/config';
import jsdoc from 'eslint-plugin-jsdoc';
import reactHooks from 'eslint-plugin-react-hooks';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import sonarjs from 'eslint-plugin-sonarjs';
import tseslint from 'typescript-eslint';

// A later block's `no-restricted-syntax` replaces an earlier one's, so every block
// setting it re-lists this.
const noMutableModuleState = {
  selector: [
    "Program > VariableDeclaration[kind!='const']",
    "Program > ExportNamedDeclaration > VariableDeclaration[kind!='const']",
  ].join(', '),
  message: 'No mutable module state — use const, or move the value inside a function.',
};

const testDoubles = ['mock', 'doMock', 'fn', 'spyOn', 'stubGlobal', 'hoisted'].map((name) => ({
  selector: `CallExpression[callee.object.name='vi'][callee.property.name='${name}']`,
  message: `no vi.${name} — pass a fake through a real parameter instead.`,
}));

export default defineConfig([
  globalIgnores([
    'dist/**',
    'coverage/**',
    'node_modules/**',
    'test-results/**',
    'playwright-report/**',
    '.stryker-tmp/**',
    'reports/**',
    'src/components/ui/**',
    'src/routeTree.gen.ts',
    'src/api/schema.d.ts',
  ]),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      ...tseslint.configs.strictTypeChecked,
      jsdoc.configs['flat/recommended-typescript'],
      sonarjs.configs.recommended,
      reactHooks.configs.flat.recommended,
      eslintReact.configs['strict-type-checked'],
      ...pluginRouter.configs['flat/recommended'],
      ...pluginQuery.configs['flat/recommended'],
    ],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'simple-import-sort': simpleImportSort,
    },
    rules: {
      'simple-import-sort/imports': 'error',
      'simple-import-sort/exports': 'error',
      complexity: ['error', 10],
      'max-statements': ['error', 40],
      'max-depth': ['error', 4],
      'max-lines': ['error', 250],
      'max-lines-per-function': ['error', 100],
      'no-console': 'error',
      'no-debugger': 'error',
      'no-restricted-syntax': ['error', noMutableModuleState],
      'jsdoc/require-jsdoc': 'off',
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-globals': [
        'error',
        { name: 'fetch', message: 'every call goes through $api; createApi(fetch?) takes the transport.' },
        { name: 'XMLHttpRequest', message: 'every call goes through $api.' },
      ],
      'no-restricted-imports': [
        'error',
        {
          paths: [
            { name: 'ag-grid-enterprise', importNames: ['AllEnterpriseModule'], message: 'add modules one by one.' },
            { name: 'ag-grid-community', importNames: ['AllCommunityModule'], message: 'add modules one by one.' },
          ],
        },
      ],
    },
  },
  {
    files: ['tests/**/*.{ts,tsx}', 'e2e/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: ['msw', 'sinon', 'jest-mock', 'testdouble', 'ts-mockito', 'proxyquire'] },
      ],
      'no-restricted-syntax': ['error', noMutableModuleState, ...testDoubles],
    },
  },
]);
