// ag-grid-enterprise's outputMissingLicenseKey, line by line.
const TRIAL_BANNER = [
  /^\*+$/,
  /^\*+ AG Grid Enterprise License \*+$/,
  /^\*+ License Key Not Found \*+$/,
  /^\* All AG Grid Enterprise features are unlocked for trial\. +\*$/,
  /^\* If you want to hide the watermark please email info@ag-grid\.com for a trial license key\. +\*$/,
];

// Only the no-key trial banner; an invalid or expired key's banner is not it.
export function isTrialBanner(text: string): boolean {
  return text
    .trim()
    .split('\n')
    .every((line) => TRIAL_BANNER.some((pattern) => pattern.test(line)));
}
