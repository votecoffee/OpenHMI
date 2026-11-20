import React from 'react';
import { PlcConnectionStatus } from './live-quality.jsx';
import { SelectedRecipe } from './recipe-controls.jsx';
import { CurrentUser } from './security.jsx';
import { LedDisplay, TagQuality, NumericDisplay, StaticLabel, ScreenSymbol, TimeDisplay, TextDisplay, annotationSymbols } from './display-controls.jsx';

export function createReadoutsPalette(catalog, fields) {
  const {
    tagField, browserTag, labelField, integerTag,
    numericFields, numericDefaults,
  } = fields;
  return {
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
  };
}
