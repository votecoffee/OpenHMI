import { createInputsPalette } from './palette-inputs.jsx';
import { createImagesPalette } from './palette-images.jsx';
import { createProcessPalette } from './palette-process.jsx';
import { createMachinePalette } from './palette-machine.jsx';
import { createReadoutsPalette } from './palette-readouts.jsx';

export const paletteFactories = [
  createInputsPalette,
  createImagesPalette,
  createProcessPalette,
  createMachinePalette,
  createReadoutsPalette,
];

// Preserve the established designer order when composing independent families.
const componentOrder = [
  'Trend', 'WebBrowser', 'Faceplate', 'MultiState',
  'ModeSelector', 'Bitfield', 'StackLight', 'PermissiveList',
  'NumericInput', 'NumericStepper', 'Slider', 'StaticImage',
  'StateImage', 'PositionImage', 'RotationImage', 'MultiStateImage',
  'StaticLabel', 'ScreenSymbol', 'Sparkline', 'SetpointComparison',
  'ProgressBar', 'CurrentUser', 'DateTimeDisplay', 'DurationDisplay',
  'TextDisplay', 'TextInput', 'TextArea', 'BarcodeInput',
  'DateTimeInput', 'Dropdown', 'RadioGroup', 'Checkbox',
  'ToggleSwitch', 'SelectedRecipe', 'PlcConnectionStatus', 'TagQuality',
  'LedDisplay', 'NumericDisplay', 'Indicator', 'AnalogRange',
  'TankLevel', 'RadialGauge', 'BarGraph', 'XYChart',
  'PieChart', 'RadarChart', 'AlarmIndicator', 'ActionButton',
];

export function createPaletteComponents(catalog, fields, getConfig) {
  const components = {};
  for (const factory of paletteFactories) {
    for (const [name, definition] of Object.entries(factory(catalog, fields, getConfig))) {
      if (Object.hasOwn(components, name)) throw new Error(`Duplicate palette component: ${name}`);
      components[name] = definition;
    }
  }
  if (Object.keys(components).length !== componentOrder.length || componentOrder.some(name => !Object.hasOwn(components, name))) {
    throw new Error('Palette families and component order must contain the same controls');
  }
  return Object.fromEntries(componentOrder.map(name => [name, components[name]]));
}
