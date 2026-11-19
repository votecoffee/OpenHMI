import React from 'react';
import { DateTimeLimit, EditControl, MAX_UTC_EPOCH, NumericInput, TextInput, TextArea, DateTimeInput, BarcodeInput } from './edit-control.jsx';

export function createInputsPalette(catalog, fields) {
  const {
    groupsField, browserTag, limitTag, labelField,
    requestedTag, writableText, writableBoolean, writableChoice,
    discrete, textFields, textDefaults, numericEditFields,
    sliderTag, numericDefaults,
  } = fields;
  return {
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
  };
}
