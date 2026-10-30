// Refuses any run without KB_UI_URL. A globalSetup rather than a throw in the
// config: knip loads the config too, and must not need a stack to do so.
export default function requireUiUrl(): void {
  if (!process.env['KB_UI_URL']) {
    throw new Error(
      'KB_UI_URL is not set: run the e2e suite with `make ui-e2e`, which starts its own kb-e2e stack and sets it.',
    );
  }
}
