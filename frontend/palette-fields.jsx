import React from 'react';
import { ChoiceFields, DiscreteInput } from './discrete-input.jsx';
import { StateFields } from './machine-state.jsx';
import { ImageField } from './state-image.jsx';
import { ChartFields } from './charts.jsx';

// Build fresh field descriptors for each project/catalog; never share mutable options.
export function createPaletteFields(catalog) {
  const groupsField = { type: 'custom', render: ({ value = [], onChange }) => <fieldset className="security-group-choice"><legend>Allowed HMI groups (any selected)</legend>
    {catalog.security_groups.map(group => <label key={group}><input type="checkbox" checked={value.includes(group)} onChange={event => onChange(event.target.checked ? [...value, group] : value.filter(item => item !== group))} />{group}</label>)}
    <small>No groups selected: use the user's operation permission.</small></fieldset> };
  const tagField = type => ({ type: 'select', label: 'Tag', options: catalog.tags
    .filter(tag => tag.type === type).map(tag => ({ label: tag.name, value: tag.name })) });
  const browserTag = (label, unbound, predicate) => ({ type: 'select', label, options: [
    { label: unbound, value: '' }, ...catalog.tags.filter(predicate).map(tag => ({ label: tag.name, value: tag.name })),
  ] });
  const limitTag = label => ({ type: 'select', label, options: [{ label: 'Fixed HMI value', value: '' }, ...catalog.tags.filter(tag => tag.type === 'number').map(tag => ({ label: tag.name, value: tag.name }))] });
  const labelField = { type: 'text', label: 'Label' };
  const showImageLabel = { type: 'select', label: 'Show label and state text', options: [
    { label: 'Yes', value: true }, { label: 'No', value: false },
  ] };
  const integerTag = tag => tag.integer && tag.unscaled !== false;
  const requestedTag = tag => integerTag(tag) && tag.writable;
  const writableText = tag => tag.writable && tag.type === 'string';
  const writableBoolean = tag => tag.writable && tag.type === 'boolean';
  const writableChoice = tag => requestedTag(tag) || writableText(tag);
  const discrete = (kind, label, predicate, choice = false) => {
    const tag = catalog.tags.find(predicate);
    const values = tag?.type === 'string' ? ['0', '1'] : [0, 1];
    return {
      label, fields: { label: labelField, tag: browserTag('Tag', 'Choose a writable tag', predicate),
        security_groups: groupsField, ...(choice ? { options: { type: 'custom', render: ({ value, onChange }) =>
          <ChoiceFields value={value} onChange={onChange} /> } } : {}) },
      defaultProps: { label, tag: tag?.name || '', security_groups: [],
        ...(choice ? { options: values.map((value, index) => ({ value, label: 'Choice ' + (index + 1) })) } : {}) },
      render: props => <DiscreteInput {...props} kind={kind} />,
    };
  };
  const statesField = { type: 'custom', render: ({ value, onChange }) => <StateFields value={value} onChange={onChange} /> };
  const defaultStates = [
    { value: 0, label: 'Stopped', symbol: 'square', color: '#555555' },
    { value: 1, label: 'Running', symbol: 'circle', color: '#333333' },
  ];
  const numericFields = { label: labelField, tag: tagField('number'), unit: { type: 'text', label: 'Units' },
    decimals: { type: 'select', label: 'Decimal places', options: [0, 1, 2, 3, 4].map(value => ({ label: String(value), value })) } };
  const textFields = { label: labelField, tag: tagField('string'),
    min_length: { type: 'number', label: 'Minimum length' }, max_length: { type: 'number', label: 'Maximum length' },
    min_length_tag: limitTag('Minimum length from tag'), max_length_tag: limitTag('Maximum length from tag'), security_groups: groupsField };
  const textDefaults = { label: 'Operator text', tag: 'OperatorText', min_length: 0, max_length: 82, security_groups: [] };
  const numericEditFields = { ...numericFields, minimum: { type: 'number', label: 'Minimum' },
    maximum: { type: 'number', label: 'Maximum' }, minimum_tag: limitTag('Minimum from tag'),
    maximum_tag: limitTag('Maximum from tag'), security_groups: groupsField };
  const sliderTag = tag => tag.type === 'number' && tag.writable && (!tag.integer || tag.unscaled !== false);
  const numericDefaults = { label: 'Tank level', tag: 'TankLevel', unit: '%', decimals: 1 };
  const scaleFields = { minimum: { type: 'number', label: 'Scale minimum' }, maximum: { type: 'number', label: 'Scale maximum' } };
  const motionImageFields = { ...numericFields, ...scaleFields, show_label: showImageLabel,
    image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="Motion image" /> } };
  const analogFields = { ...numericFields, ...scaleFields,
    normal_low: { type: 'number', label: 'Normal low' }, normal_high: { type: 'number', label: 'Normal high' } };
  const analogDefaults = { ...numericDefaults, minimum: 0, maximum: 100, normal_low: 20, normal_high: 80 };
  const chartField = kind => ({ type: 'custom', render: ({ value, onChange }) =>
    <ChartFields value={value} onChange={onChange} catalog={catalog} kind={kind} /> });
  const conditionTag = label => ({ type: 'select', label, options: [{ label: 'Always / none', value: '' }, ...catalog.tags.filter(tag => tag.type === 'boolean').map(tag => ({ label: tag.name, value: tag.name }))] });
  const commonFields = { visible_tag: conditionTag('Visible when tag is true'), enabled_tag: conditionTag('Enabled when tag is true'), color_tag: conditionTag('Color when tag is true'), active_color: { type: 'select', label: 'Active value color', options: [['#002878', 'Navy'], ['#333333', 'Dark gray'], ['#fa3232', 'Priority 1 red'], ['#fff546', 'Priority 2 yellow'], ['#ff9600', 'Priority 3 orange'], ['#ff64c8', 'Priority 4 magenta']].map(([value, label]) => ({ value, label })) } };
  return {
    groupsField, tagField, browserTag, limitTag,
    labelField, showImageLabel, integerTag, requestedTag,
    writableText, writableBoolean, writableChoice, discrete,
    statesField, defaultStates, numericFields, textFields,
    textDefaults, numericEditFields, sliderTag, numericDefaults,
    scaleFields, motionImageFields, analogFields, analogDefaults,
    chartField, commonFields,
  };
}
