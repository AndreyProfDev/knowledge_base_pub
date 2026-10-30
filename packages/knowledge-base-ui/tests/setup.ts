import { cleanup } from '@testing-library/react';
import { setupAgTestIds } from 'ag-grid-community';
import { toast } from 'sonner';
import { afterEach } from 'vitest';

import { fakeMatchMedia, setSystemDark } from './media';

// package.json's scripts run under LC_ALL=de_DE.UTF-8 so unpinned English text fails a test; under an
// English default (a bare `npx vitest`, an ICU without de) that guard would pass everything.
const defaultLocale = new Intl.NumberFormat().resolvedOptions().locale;
if (!defaultLocale.startsWith('de')) {
  throw new Error(`default locale is ${defaultLocale}, not de: run tests via the npm scripts (LC_ALL=de_DE.UTF-8)`);
}

// Grid cells carry `data-testid`s from agTestIdFor.
setupAgTestIds();

// vitest runs without globals, so testing-library cannot register its own cleanup. Sonner's store is
// module-level and replays active toasts to the next Toaster.
afterEach(() => {
  cleanup();
  toast.dismiss();
  localStorage.clear();
  document.documentElement.className = '';
  setSystemDark(false);
});

// jsdom gaps, filled; not mocks of the code under test.

class NoopResizeObserver {
  observe(): void {
    /* jsdom has no layout to observe */
  }
  unobserve(): void {
    /* jsdom has no layout to observe */
  }
  disconnect(): void {
    /* jsdom has no layout to observe */
  }
}
globalThis.ResizeObserver = NoopResizeObserver;

// The router restores scroll on every navigation; jsdom has no layout to scroll.
window.scrollTo = () => undefined;

// Radix Select scrolls its focused option into view and checks pointer capture on open; a sonner toast
// captures the pointer on press.
Element.prototype.scrollIntoView = () => undefined;
Element.prototype.setPointerCapture = () => undefined;
Element.prototype.hasPointerCapture = () => false;
Element.prototype.releasePointerCapture = () => undefined;

window.matchMedia = fakeMatchMedia;

// A browser's Request resolves a relative URL (createApi's `/api`) against the page; Node's, which jsdom
// leaves in place, throws.
class PageRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input instanceof Request ? input : new URL(input, window.location.href), init);
  }
}
globalThis.Request = PageRequest;

// jsdom's offsetParent is always null; AG Grid positions its context menu against the grid's.
Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
  configurable: true,
  get(this: HTMLElement) {
    return this.parentElement;
  },
});

// AG Grid writes cell text through innerText, which jsdom lacks.
Object.defineProperty(HTMLElement.prototype, 'innerText', {
  configurable: true,
  get(this: HTMLElement) {
    return this.textContent;
  },
  set(this: HTMLElement, value: string) {
    this.textContent = value;
  },
});
