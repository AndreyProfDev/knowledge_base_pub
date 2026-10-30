// Mutation testing over the scope of the 100% coverage gate; `make ui-mutation`.
// No coverageAnalysis (the vitest runner always runs perTest), no testFiles
// (stryker-js#6209: static mutants then report Survived without being run) and
// no ignoreStatic (it would hide untested module-level code from the score).
export default {
  // The vitest runner, wrapped so Vitest 5 runs a mutant's covering tests (see the file).
  plugins: ['./stryker-vitest-runner.mjs'],
  testRunner: 'vitest',
  mutate: ['src/lib/**/*.ts'],
  // `json` is load-bearing: `make ui-mutation` fails unless reports/mutation/mutation.json has mutants.
  reporters: ['clear-text', 'progress', 'html', 'json'],
  jsonReporter: { fileName: 'reports/mutation/mutation.json' },
  thresholds: { high: 100, low: 100, break: 100 },
  // A mutant runs every test of its covering files (all tests if static), route tests
  // waiting on findBy* included: at the 5000 default search-params.ts's one survivor
  // timed out and scored 100%; at 20000 and at 40000 it survives and none time out.
  timeoutMS: 20000,
  // Each runner is a process plus a Vitest worker thread over jsdom, so the default (cores - 1,
  // 23 here on 24 threads: 8 P-cores with HT + 8 E-cores) queues 40-75 runnable threads and slow,
  // terminating mutants time out. ag-grid-banner + api + grid-theme: at 23, 29 timeouts in 2:49;
  // at 12, 8 (static) in 3:48; at 8, none (all Killed or Survived) in 3:52. Full run at 8:
  // 527 mutants, 0 timeouts in 8:47 (at 23: 62 in 8:33); at timeoutMS 40000 every status is equal.
  // A share, not a fixed 8, so fewer cores get fewer runners: Stryker rounds cores x 33%, which is
  // 8 on 24 threads and 1 on 2 CPUs (a fixed 8 there timed out 5 search-params.ts mutants).
  // Stryker counts a Timeout as detected, so `make ui-mutation` also fails on any Timeout.
  concurrency: '33%',
};
