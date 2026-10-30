import {
  CellStyleModule,
  ClientSideRowModelModule,
  type Module,
  RenderApiModule,
  TooltipModule,
} from 'ag-grid-community';
import { ContextMenuModule, SetFilterModule, StatusBarModule } from 'ag-grid-enterprise';

// One by one, not AllEnterpriseModule: the bundle budget would not hold it.
export const gridModules: Module[] = [
  ClientSideRowModelModule,
  TooltipModule,
  CellStyleModule,
  RenderApiModule,
  ContextMenuModule,
  SetFilterModule,
  StatusBarModule,
];

// `exactOptionalPropertyTypes` rejects `licenseKey={undefined}`; no key runs the grid as a local trial.
export function licenceProps(key: string | undefined): Record<string, never> | { licenseKey: string } {
  return key ? { licenseKey: key } : {};
}
