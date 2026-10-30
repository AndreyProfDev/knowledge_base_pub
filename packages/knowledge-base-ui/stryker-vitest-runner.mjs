// The 'vitest' test runner of @stryker-mutator/vitest-runner 10.0.0, filtering a mutant's
// tests by file instead of by name. 10.0.0 builds the name filter from suite and test names
// joined with ' ', while Vitest 5 matches testNamePattern against them joined with ' > '
// (https://vitest.dev/config/testnamepattern), so every test inside a `describe` is skipped
// and its mutant reports Survived having run nothing. Running every test of the covering
// files is a superset of the covering tests. Delete this file and `plugins` in
// stryker.config.mjs once a vitest-runner release joins names with ' > '.
import * as vitestRunner from '@stryker-mutator/vitest-runner';

const [vitestPlugin] = vitestRunner.strykerPlugins;

function createFileFilteredVitestRunner(injector) {
  const runner = vitestPlugin.factory(injector);
  const run = runner.run.bind(runner);
  runner.run = ({ testIds = [], ...options } = {}) =>
    run(testIds.length ? { ...options, testFiles: [...new Set(testIds.map((id) => id.split('#')[0]))] } : options);
  return runner;
}
createFileFilteredVitestRunner.inject = vitestPlugin.factory.inject;

export const strykerValidationSchema = vitestRunner.strykerValidationSchema;
export const strykerPlugins = [{ ...vitestPlugin, factory: createFileFilteredVitestRunner }];
