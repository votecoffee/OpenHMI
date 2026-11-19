import React from 'react';
import { PlcConnectionStatus } from './live-quality.jsx';
import { controlTypes } from './model.mjs';
import { SelectedRecipe } from './recipes.jsx';
import { CurrentUser } from './security.jsx';
import { WebBrowser } from './web-browser.jsx';
import { ImageField, ImageStatesFields, MultiStateImage, MotionImage, StateImage, StaticImage } from './state-image.jsx';
import { DateTimeLimit, EditControl, MAX_UTC_EPOCH, NumericInput, TextInput, TextArea, DateTimeInput, BarcodeInput } from './edit-control.jsx';
import { Bitfield, BitfieldFields, MultiState, ModeSelector, PermissiveList, StackLight, StackLightFields, PermissiveFields } from './machine-state.jsx';
import { Sparkline, LiveTrend, TrendFields } from './trend.jsx';
import { TrendRecordingFields } from './trend-recording.jsx';
import { PieChart, LiveChart, XYChart, XYFields, chartSeries } from './charts.jsx';
import { LedDisplay, TagQuality, NumericDisplay, StaticLabel, ScreenSymbol, ProgressBar, TimeDisplay, TextDisplay, Indicator, annotationSymbols } from './display-controls.jsx';
import { SetpointComparison, AnalogRange } from './process-controls.jsx';
import { AlarmIndicator } from './alarm-controls.jsx';
import { ActionButton } from './action-button.jsx';
import { ScreenFrame } from './screen-frame.jsx';
import { Conditional } from './conditional-control.jsx';
import { FaceplateInstance } from './faceplate.jsx';
import { createPaletteFields } from './palette-fields.jsx';

export { ScreenControls, ScreenFrame } from './screen-frame.jsx';
export { PrioritySymbol } from './alarm-controls.jsx';

export function createConfig(catalog) {
  const {
    groupsField, tagField, browserTag, limitTag,
    labelField, showImageLabel, integerTag, requestedTag,
    writableText, writableBoolean, writableChoice, discrete,
    statesField, defaultStates, numericFields, textFields,
    textDefaults, numericEditFields, sliderTag, numericDefaults,
    scaleFields, motionImageFields, analogFields, analogDefaults,
    chartField, commonFields,
  } = createPaletteFields(catalog);
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
    components: {
      Trend: { label: 'Trend', fields: {
        label: labelField, seconds: { type: 'number', label: 'Time window (seconds)', min: 10, max: 604800 },
        pens: { type: 'custom', render: ({ value, onChange }) => <TrendFields value={value} onChange={onChange} catalog={catalog} /> },
        recording: { type: 'custom', render: ({ value, onChange }) => <TrendRecordingFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Process trend', pens: { tags: ['TankLevel'], series: {} }, seconds: 300 },
      render: props => <LiveTrend {...props} catalog={catalog} /> },
      WebBrowser: { label: 'Web Browser / Camera View', fields: {
        label: labelField,
        scheme: { type: 'select', label: 'Scheme', options: [{ label: 'HTTPS', value: 'https' }, { label: 'HTTP', value: 'http' }] },
        hosts: { type: 'text', label: 'Approved hosts (comma-separated)' },
        port: { type: 'number', label: 'Port (blank uses scheme default)', min: 1, max: 65535 },
        path: { type: 'text', label: 'Approved path' },
        address_tag: browserTag('Address from tag', 'Fixed address (first approved host)', tag => tag.type === 'string'),
        refresh_tag: browserTag('Refresh from tag', 'Manual refresh only', tag => tag.type === 'boolean' || tag.integer),
      }, defaultProps: { label: 'Camera view', scheme: 'https', hosts: '', port: null, path: '/', address_tag: '', refresh_tag: '' },
      render: WebBrowser },
      Faceplate: { label: 'UDT faceplate', fields: { label: labelField, template: { type: 'select', label: 'Definition', options: (catalog.faceplates || []).map(item => ({ label: item.name, value: item.id })) }, root_tag: tagField('struct') },
        defaultProps: { label: 'Equipment', template: catalog.faceplates?.[0]?.id || '', root_tag: catalog.tags.find(tag => tag.type === 'struct')?.name || '' },
        render: props => <FaceplateInstance {...props} config={config} /> },
      MultiState: { label: 'Multi-state indicator', fields: {
        label: labelField, tag: browserTag('State tag', 'Choose an integer tag', integerTag), states: statesField,
      }, defaultProps: { label: 'Machine state', tag: 'AlarmWord', states: defaultStates }, render: MultiState },
      ModeSelector: { label: 'Mode selector', fields: {
        label: labelField, tag: browserTag('Mode request tag', 'Choose a writable integer tag', requestedTag),
        confirmed_tag: browserTag('PLC confirmed mode tag', 'Choose a separate integer tag', integerTag),
        states: statesField, security_groups: groupsField,
        presentation: { type: 'select', label: 'Presentation', options: [
          { label: 'Dropdown', value: 'dropdown' }, { label: 'Segmented buttons', value: 'segments' },
        ] },
      }, defaultProps: { label: 'Machine mode', tag: catalog.tags.find(requestedTag)?.name || '', confirmed_tag: '',
        states: [{ ...defaultStates[0], label: 'Manual' }, { ...defaultStates[1], label: 'Auto' }],
        presentation: 'dropdown', security_groups: [] }, render: ModeSelector },
      Bitfield: { label: 'Bitfield display', fields: {
        label: labelField, tag: browserTag('Tag', 'Choose an unscaled integer tag', integerTag),
        bits: { type: 'custom', render: ({ value, onChange }) => <BitfieldFields value={value} onChange={onChange} /> },
      }, defaultProps: { label: 'Status word', tag: 'AlarmWord', bits: [
        { bit: 0, label: 'Bit 0' }, { bit: 1, label: 'Bit 1' },
      ] }, render: props => <Bitfield {...props} /> },
      StackLight: { label: 'Stack light', fields: {
        label: labelField,
        orientation: { type: 'select', label: 'Orientation', options: [
          { label: 'Vertical', value: 'vertical' }, { label: 'Horizontal', value: 'horizontal' },
        ] },
        lamps: { type: 'custom', render: ({ value, onChange }) =>
          <StackLightFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Machine signals', orientation: 'vertical', lamps: [
        { tag: 'ProcessAlarm', label: 'Fault', active_when: true, color: '#b3272a' },
        { tag: 'MotorRunning', label: 'Running', active_when: true, color: '#36744b' },
      ] }, render: props => <StackLight {...props} /> },
      PermissiveList: { label: 'Permissive / interlock list', fields: {
        label: labelField, checks: { type: 'custom', render: ({ value, onChange }) =>
          <PermissiveFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Start permissives', checks: [{ tag: 'MotorRunning', label: 'Motor running', expected: false }] },
      render: PermissiveList },
      NumericInput: { label: 'Numeric input', fields: numericEditFields,
        defaultProps: { ...numericDefaults, label: 'Tank setpoint', minimum: 0, maximum: 100, security_groups: [] }, render: NumericInput },
      NumericStepper: { label: 'Numeric stepper', fields: { ...numericEditFields,
        tag: browserTag('Tag', 'Choose a writable numeric tag', sliderTag),
        step: { type: 'number', label: 'Increment', min: 0.00000001, max: 1e12 } },
        defaultProps: { ...numericDefaults, label: 'Setpoint', unit: '', tag: catalog.tags.find(sliderTag)?.name || '',
          minimum: 0, maximum: 100, step: 1, security_groups: [] },
        render: props => <EditControl {...props} stepper /> },
      Slider: { label: 'Slider', fields: { ...numericEditFields, tag: browserTag('Tag', 'Choose a writable numeric tag', sliderTag) },
        defaultProps: { ...numericDefaults, label: 'Setpoint slider', unit: '', tag: catalog.tags.find(sliderTag)?.name || '',
          minimum: 0, maximum: 100, security_groups: [] },
        render: props => <EditControl {...props} slider sliderInteger={!!catalog.tags.find(tag => tag.name === props.tag)?.integer} /> },
      StaticImage: { label: 'Image', fields: {
        label: labelField, alt_text: { type: 'text', label: 'Alternative text' },
        image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="Project image" /> },
        fit: { type: 'select', label: 'Image fit', options: [
          { label: 'Contain', value: 'contain' }, { label: 'Cover', value: 'cover' }, { label: 'Stretch', value: 'fill' },
        ] },
        show_label: { ...showImageLabel, label: 'Show caption' },
      }, defaultProps: { label: 'Image', image: '', alt_text: '', fit: 'contain', show_label: true },
      render: props => <StaticImage {...props} /> },
      StateImage: { label: 'State image', fields: {
        label: labelField, tag: tagField('boolean'),
        on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' },
        on_image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="ON image" /> },
        off_image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="OFF image" /> },
        show_label: showImageLabel,
      }, defaultProps: { label: 'Machine image', tag: 'MotorRunning', on_image: '', off_image: '',
        on_text: 'ON', off_text: 'OFF', show_label: true }, render: props => <StateImage {...props} /> },
      PositionImage: { label: 'Position image', fields: {
        ...motionImageFields,
        direction: { type: 'select', label: 'Travel direction', options: [
          { label: 'Left to right', value: 'left_to_right' }, { label: 'Right to left', value: 'right_to_left' },
          { label: 'Bottom to top', value: 'bottom_to_top' }, { label: 'Top to bottom', value: 'top_to_bottom' },
        ] },
        size_percent: { type: 'number', label: 'Marker size (%)', min: 10, max: 60 },
      }, defaultProps: { ...numericDefaults, label: 'Axis position', minimum: 0, maximum: 100, direction: 'left_to_right',
        size_percent: 25, image: '', show_label: true }, render: MotionImage },
      RotationImage: { label: 'Rotation image', fields: {
        ...motionImageFields,
        angle_start: { type: 'number', label: 'Start angle (degrees)', min: -360, max: 360 },
        angle_end: { type: 'number', label: 'End angle (degrees)', min: -360, max: 360 },
        size_percent: { type: 'number', label: 'Marker size (%)', min: 10, max: 70 },
      }, defaultProps: { ...numericDefaults, label: 'Rotation', minimum: 0, maximum: 100, angle_start: 0, angle_end: 360,
        size_percent: 50, image: '', show_label: true }, render: props => <MotionImage {...props} rotation /> },
      MultiStateImage: { label: 'Multi-state image', fields: {
        label: labelField, tag: browserTag('Tag', 'Choose an unscaled integer tag', integerTag),
        states: { type: 'custom', render: props => <ImageStatesFields key={props.id} {...props} /> },
        show_label: showImageLabel,
      }, defaultProps: { label: 'Machine position', tag: 'AlarmWord', show_label: true, states: [
        { value: 0, label: 'Stopped', image: '' }, { value: 1, label: 'Running', image: '' },
      ] }, render: props => <MultiStateImage {...props} /> },
      StaticLabel: { label: 'Static label', fields: {
        label: labelField, font_size: { type: 'number', label: 'Font size (px)', min: 8, max: 72 },
        alignment: { type: 'select', label: 'Text alignment', options: [
          { label: 'Start', value: 'start' }, { label: 'Center', value: 'center' }, { label: 'End', value: 'end' },
        ] },
        weight: { type: 'select', label: 'Text weight', options: [
          { label: 'Normal', value: 'normal' }, { label: 'Bold', value: 'bold' },
        ] },
      }, defaultProps: { label: 'Machine section', font_size: 16, alignment: 'start', weight: 'normal' }, render: StaticLabel },
      ScreenSymbol: { label: 'Symbol', fields: {
        label: { type: 'text', label: 'Accessible label' },
        symbol: { type: 'select', label: 'Shape', options: Object.entries(annotationSymbols)
          .map(([value, { label }]) => ({ value, label })) },
        size: { type: 'number', label: 'Symbol size (px)', min: 12, max: 96 },
        rotation: { type: 'select', label: 'Rotation', options: [0, 90, 180, 270]
          .map(value => ({ value, label: String(value) + ' degrees' })) },
      }, defaultProps: { label: 'Direction of travel', symbol: 'arrow', size: 28, rotation: 0 }, render: ScreenSymbol },
      Sparkline: { label: 'Sparkline', fields: { ...numericFields,
        seconds: { type: 'number', label: 'History window (seconds)', min: 5, max: 3600 } },
        defaultProps: { ...numericDefaults, label: 'Recent tank level', seconds: 60 }, render: props => <Sparkline {...props} /> },
      SetpointComparison: { label: 'Setpoint comparison', fields: {
        ...numericFields, tag: { ...numericFields.tag, label: 'Process value tag' },
        setpoint_tag: browserTag('Setpoint tag', 'Choose a numeric tag', tag => tag.type === 'number'),
        tolerance: { type: 'number', label: 'Tolerance', min: 0 },
        tolerance_tag: limitTag('Tolerance from tag'),
      }, defaultProps: { ...numericDefaults, label: 'Setpoint comparison', setpoint_tag: '', tolerance: 1, tolerance_tag: '' },
      render: SetpointComparison },
      ProgressBar: { label: 'Progress bar', fields: { ...numericFields, ...scaleFields },
        defaultProps: { ...numericDefaults, label: 'Progress', minimum: 0, maximum: 100 }, render: ProgressBar },
      CurrentUser: { label: 'Current login user', fields: { label: labelField }, defaultProps: { label: 'Current user' }, render: CurrentUser },
      DateTimeDisplay: { label: 'Date/time display', fields: {
        label: labelField, tag: browserTag('Tag', 'Choose an unscaled integer tag', integerTag),
      }, defaultProps: { label: 'UTC timestamp', tag: catalog.tags.find(integerTag)?.name || 'AlarmWord' }, render: TimeDisplay },
      DurationDisplay: { label: 'Duration display', fields: {
        label: labelField, tag: tagField('number'),
        source_unit: { type: 'select', label: 'Source units', options: [
          { label: 'Milliseconds', value: 'milliseconds' }, { label: 'Seconds', value: 'seconds' },
        ] },
        decimals: { type: 'select', label: 'Fractional places', options: [0, 1, 2, 3].map(value => ({ label: String(value), value })) },
      }, defaultProps: { label: 'Elapsed time', tag: 'TankLevel', source_unit: 'milliseconds', decimals: 0 },
      render: props => <TimeDisplay {...props} duration /> },
      TextDisplay: { label: 'Text display', fields: { label: labelField, tag: tagField('string') },
        defaultProps: { label: 'Status text', tag: 'OperatorText' }, render: TextDisplay },
      TextInput: { label: 'Text input', fields: textFields, defaultProps: textDefaults, render: TextInput },
      TextArea: { label: 'Text area', fields: { ...textFields, tag: browserTag('Tag', 'Choose a writable text tag', writableText) },
        defaultProps: { ...textDefaults, label: 'Operator notes', tag: catalog.tags.find(writableText)?.name || '' }, render: TextArea },
      BarcodeInput: { label: 'Barcode scanner input', fields: { ...textFields, tag: browserTag('Tag', 'Choose a writable text tag', writableText) },
        defaultProps: { ...textDefaults, label: 'Barcode', tag: catalog.tags.find(writableText)?.name || '', min_length: 1 }, render: BarcodeInput },
      DateTimeInput: { label: 'Date/time input', fields: {
        label: labelField, tag: browserTag('Tag', 'Choose a writable integer tag', requestedTag),
        minimum: { type: 'custom', render: props => <DateTimeLimit {...props} label="Earliest (UTC)" /> },
        maximum: { type: 'custom', render: props => <DateTimeLimit {...props} label="Latest (UTC)" /> },
        minimum_tag: limitTag('Earliest from tag'), maximum_tag: limitTag('Latest from tag'), security_groups: groupsField,
      }, defaultProps: { label: 'UTC timestamp', tag: catalog.tags.find(requestedTag)?.name || '',
        minimum: 0, maximum: MAX_UTC_EPOCH, security_groups: [] }, render: DateTimeInput },
      Dropdown: discrete('dropdown', 'Dropdown', writableChoice, true),
      RadioGroup: discrete('radio_group', 'Radio group', writableChoice, true),
      Checkbox: discrete('checkbox', 'Checkbox', writableBoolean),
      ToggleSwitch: discrete('toggle_switch', 'Toggle switch', writableBoolean),
      SelectedRecipe: { label: 'Selected recipe', fields: { label: labelField }, defaultProps: { label: 'Loaded recipe' }, render: SelectedRecipe },
      PlcConnectionStatus: { label: 'PLC connection status', fields: {
        label: labelField, connection: { type: 'select', label: 'PLC connection', options: [
          { label: 'Choose a PLC connection', value: '' },
          ...(catalog.connections || []).map(route => ({ label: route.name, value: route.id })),
        ] },
      }, defaultProps: { label: 'PLC status', connection: catalog.connections?.[0]?.id || '' },
      render: props => <PlcConnectionStatus {...props} /> },
      TagQuality: { label: 'Tag quality', fields: {
        label: labelField, tag: browserTag('Tag', 'Choose a tag', () => true),
        show_age: { type: 'select', label: 'Show sample age', options: [
          { label: 'Yes', value: true }, { label: 'No', value: false },
        ] },
      }, defaultProps: { label: 'Tag status', tag: 'TankLevel', show_age: true }, render: TagQuality },
      LedDisplay: { label: 'Numeric LED display', fields: { ...numericFields,
        digits: { type: 'number', label: 'Digit positions', min: 2, max: 12 },
      }, defaultProps: { ...numericDefaults, label: 'Numeric readout', digits: 5 }, render: LedDisplay },
      NumericDisplay: { label: 'Numeric display', fields: numericFields, defaultProps: numericDefaults, render: NumericDisplay },
      Indicator: {
        label: 'Indicator', fields: { label: labelField, tag: tagField('boolean'), on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' } },
        defaultProps: { label: 'Motor', tag: 'MotorRunning', on_text: 'ON', off_text: 'OFF' }, render: Indicator,
      },
      AnalogRange: { label: 'Analog range', fields: analogFields,
        defaultProps: { ...analogDefaults, label: 'Tank operating range' }, render: AnalogRange },
      TankLevel: { label: 'Tank level indicator', fields: analogFields,
        defaultProps: analogDefaults, render: props => <AnalogRange {...props} kind="tank" /> },
      RadialGauge: { label: 'Radial gauge', fields: analogFields,
        defaultProps: { ...analogDefaults, label: 'Tank level gauge' }, render: props => <AnalogRange {...props} kind="gauge" /> },
      BarGraph: { label: 'Bar graph', fields: { label: labelField, ...scaleFields, unit: numericFields.unit, series: chartField('bar') },
        defaultProps: { label: 'Process comparison', minimum: 0, maximum: 100, unit: '', series: [chartSeries('TankLevel', false)] },
        render: LiveChart },
      XYChart: { label: 'XY chart', fields: {
        label: labelField, decimals: numericFields.decimals,
        x_minimum: { type: 'number', label: 'X minimum' }, x_maximum: { type: 'number', label: 'X maximum' },
        y_minimum: { type: 'number', label: 'Y minimum' }, y_maximum: { type: 'number', label: 'Y maximum' },
        x_unit: { type: 'text', label: 'X units' }, y_unit: { type: 'text', label: 'Y units' },
        series: { type: 'custom', render: ({ value, onChange }) =>
          <XYFields value={value} onChange={onChange} catalog={catalog} /> },
      }, defaultProps: { label: 'Live XY values', decimals: 1, x_minimum: 0, x_maximum: 100, x_unit: '',
        y_minimum: 0, y_maximum: 100, y_unit: '', series: [{ x_tag: 'TankLevel', y_tag: 'AlarmWord', label: '' }] },
      render: props => <XYChart {...props} /> },
      PieChart: { label: 'Pie chart', fields: { label: labelField, unit: numericFields.unit, series: chartField('pie') },
        defaultProps: { label: 'Part totals', unit: '', series: ['TankLevel', 'RecipeRevision'].map(tag => chartSeries(tag, false)) },
        render: props => <PieChart {...props} /> },
      RadarChart: { label: 'Radar chart', fields: { label: labelField, series: chartField('radar') },
        defaultProps: { label: 'Process profile', series: catalog.tags.filter(tag => tag.type === 'number').slice(0, 3).map(tag => chartSeries(tag.name, true)) },
        render: props => <LiveChart {...props} radar /> },
      AlarmIndicator: {
        label: 'Alarm indicator', fields: { label: labelField, tag: tagField('boolean'), priority: { type: 'select', label: 'Alarm priority',
          options: [1, 2, 3, 4].map(value => ({ label: `Priority ${value}`, value })) } },
        defaultProps: { label: 'Process alarm', tag: 'ProcessAlarm', priority: 2 }, render: AlarmIndicator,
      },
      ActionButton: {
        label: 'Action button', fields: { label: labelField, security_groups: groupsField,
          mode: { type: 'select', label: 'Action type', options: [['python', 'Python action'], ['command', 'PLC command transaction'], ['set', 'Set tag'], ['toggle', 'Toggle Boolean tag'], ['navigate', 'Navigate to screen'], ['popup', 'Open popup'], ['close_popup', 'Close popup']].map(([value, label]) => ({ value, label })) },
          command: { type: 'select', label: 'PLC command contract', options: (catalog.commands || []).map(item => ({ label: item.name, value: item.id })) },
          target: { type: 'select', label: 'Target tag', options: catalog.tags.filter(tag => tag.type !== 'struct').map(tag => ({ label: tag.name, value: tag.name })) },
          value: { type: 'custom', render: ({ value = false, onChange }) => <fieldset><legend>Value to write</legend><select aria-label="Action value type" value={typeof value} onChange={event => onChange(event.target.value === 'boolean' ? false : event.target.value === 'number' ? 0 : '')}><option value="boolean">Boolean</option><option value="number">Number</option><option value="string">Text</option></select>{typeof value === 'boolean' ? <label><input type="checkbox" checked={value} onChange={event => onChange(event.target.checked)} />True</label> : <input aria-label="Action value" type={typeof value === 'number' ? 'number' : 'text'} value={value} onChange={event => onChange(typeof value === 'number' ? Number(event.target.value) : event.target.value)} />}</fieldset> },
          screen: { type: 'select', label: 'Target screen / popup', options: (catalog.screens || [{ id: 'overview', title: 'Overview' }]).map(screen => ({ label: `${screen.title}${screen.popup ? ' (popup)' : ''}`, value: screen.id })) },
          action: { type: 'select', label: 'Python action',
          options: catalog.actions.map(action => ({ label: action.label, value: action.name })) } },
        defaultProps: { label: 'Toggle simulated motor', action: 'toggle_motor', security_groups: [], mode: 'python', target: 'MotorRunning', value: false, screen: 'overview' }, render: ActionButton,
      },
    },
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
