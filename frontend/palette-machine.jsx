import React from 'react';
import { WebBrowser } from './web-browser.jsx';
import { Bitfield, BitfieldFields, MultiState, ModeSelector, PermissiveList, StackLight, StackLightFields, PermissiveFields } from './machine-state.jsx';
import { Indicator } from './display-controls.jsx';
import { AlarmIndicator } from './alarm-controls.jsx';
import { ActionButton } from './action-button.jsx';
import { FaceplateInstance } from './faceplate.jsx';

export function createMachinePalette(catalog, fields, getConfig) {
  const {
    groupsField, tagField, browserTag, labelField,
    integerTag, requestedTag, statesField, defaultStates,
  } = fields;
  return {
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
      render: props => <FaceplateInstance {...props} config={getConfig()} /> },
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
    Indicator: {
      label: 'Indicator', fields: { label: labelField, tag: tagField('boolean'), on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' } },
      defaultProps: { label: 'Motor', tag: 'MotorRunning', on_text: 'ON', off_text: 'OFF' }, render: Indicator,
    },
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
  };
}
