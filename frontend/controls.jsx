import React from 'react';
import { controlTypes } from './model.mjs';
import { NumericInput, TextInput, TextArea, DateTimeInput, BarcodeInput } from './edit-control.jsx';
import { ActionButton } from './action-button.jsx';
import { ScreenFrame } from './screen-frame.jsx';
import { Conditional } from './conditional-control.jsx';
import { createPaletteFields } from './palette-fields.jsx';
import { createPaletteComponents } from './palette-components.jsx';

export { ScreenControls, ScreenFrame } from './screen-frame.jsx';
export { PrioritySymbol } from './alarm-controls.jsx';

export function createConfig(catalog) {
  const fields = createPaletteFields(catalog);
  const { commonFields } = fields;
  const displayTypes = ['StaticLabel', 'ScreenSymbol', 'ProgressBar', 'Sparkline', 'DateTimeDisplay', 'DurationDisplay', 'StackLight', 'LedDisplay', 'TagQuality', 'PlcConnectionStatus', 'Bitfield', 'SetpointComparison', 'StateImage', 'MultiStateImage', 'PositionImage', 'RotationImage', 'StaticImage'];
  const chartTypes = ['TankLevel', 'RadialGauge', 'BarGraph', 'RadarChart', 'PieChart', 'XYChart'];
  const inputTypes = ['NumericInput', 'NumericStepper', 'Slider', 'TextInput', 'TextArea', 'BarcodeInput', 'DateTimeInput', 'Dropdown', 'RadioGroup', 'Checkbox', 'ToggleSwitch'];
  const config = {
    root: {
      fields: { title: { type: 'text', label: 'Screen name' }, columns: { type: 'select', label: 'Columns',
        options: [1, 2, 3].map(value => ({ label: String(value), value })) } },
      defaultProps: { title: 'Station overview', columns: 2 }, render: ScreenFrame,
    },
    categories: {
      hmi: { title: 'High performance HMI', components: Object.values(controlTypes)
        .filter(type => !chartTypes.includes(type) && !inputTypes.includes(type) && !displayTypes.includes(type) && (type !== 'Faceplate' || catalog.faceplates?.length)) },
      inputs: { title: 'Inputs', components: inputTypes },
      display: { title: 'Display', components: displayTypes },
      charts: { title: 'Live charts', components: chartTypes },
    },
    components: createPaletteComponents(catalog, fields, () => config),
  };
  for (const component of Object.values(config.components)) {
    component.fields = { ...component.fields, ...commonFields };
    const renderer = component.render;
    const handlesOwnEnable = renderer === NumericInput || renderer === TextInput || renderer === TextArea || renderer === DateTimeInput || renderer === BarcodeInput || renderer === ActionButton || component === config.components.Slider || component === config.components.NumericStepper;
    component.render = props => <Conditional {...props} enabled_tag={handlesOwnEnable ? '' : props.enabled_tag}>
      {renderer(props)}
    </Conditional>;
  }
  if (!catalog.faceplates?.length) delete config.components.Faceplate;
  return config;
}
