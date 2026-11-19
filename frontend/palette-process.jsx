import React from 'react';
import { Sparkline, LiveTrend, TrendFields } from './trend.jsx';
import { TrendRecordingFields } from './trend-recording.jsx';
import { PieChart, LiveChart, XYChart, XYFields, chartSeries } from './charts.jsx';
import { ProgressBar } from './display-controls.jsx';
import { SetpointComparison, AnalogRange } from './process-controls.jsx';

export function createProcessPalette(catalog, fields) {
  const {
    browserTag, limitTag, labelField, numericFields,
    numericDefaults, scaleFields, analogFields, analogDefaults,
    chartField,
  } = fields;
  return {
    Trend: { label: 'Trend', fields: {
      label: labelField, seconds: { type: 'number', label: 'Time window (seconds)', min: 10, max: 604800 },
      pens: { type: 'custom', render: ({ value, onChange }) => <TrendFields value={value} onChange={onChange} catalog={catalog} /> },
      recording: { type: 'custom', render: ({ value, onChange }) => <TrendRecordingFields value={value} onChange={onChange} catalog={catalog} /> },
    }, defaultProps: { label: 'Process trend', pens: { tags: ['TankLevel'], series: {} }, seconds: 300 },
    render: props => <LiveTrend {...props} catalog={catalog} /> },
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
  };
}
