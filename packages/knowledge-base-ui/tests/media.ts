// jsdom has no matchMedia. This one answers the OS scheme a test sets, `change` included; light by default.
const changes = new EventTarget();
const system = { dark: false };

export function setSystemDark(dark: boolean): void {
  system.dark = dark;
  changes.dispatchEvent(new Event('change'));
}

export function fakeMatchMedia(query: string): MediaQueryList {
  return {
    get matches() {
      return query === '(prefers-color-scheme: dark)' && system.dark;
    },
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: (type: string, listener: EventListener) => {
      changes.addEventListener(type, listener);
    },
    removeEventListener: (type: string, listener: EventListener) => {
      changes.removeEventListener(type, listener);
    },
    dispatchEvent: (event: Event) => changes.dispatchEvent(event),
  };
}
