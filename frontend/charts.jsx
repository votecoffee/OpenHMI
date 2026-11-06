import React, { useContext } from 'react';
import { Live, tagValue, Quality } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import './charts.css';

const validRange = (minimum, maximum) => Number.isFinite(minimum) && Number.isFinite(maximum)
  && Number.isFinite(maximum - minimum) && maximum > minimum;
const percentage = (value, minimum, maximum) => 100 * ((Math.min(maximum, Math.max(minimum, value)) - minimum) / (maximum - minimum));
const decimals = [0, 1, 2, 3, 4];

export function chartSeries(tag, radar) {
  return { tag, label: '', decimals: 1, ...(radar ? { unit: '', minimum: 0, maximum: 100 } : {}) };
}

export function ChartFields({ value = [], onChange, catalog, kind }) {
  const radar = kind === 'radar', pie = kind === 'pie';
  const tags = catalog.tags.filter(tag => tag.type === 'number');
  const minimum = radar ? 3 : pie ? 2 : 1, maximum = kind === 'bar' ? 12 : 8;
  const rowName = radar ? 'axis' : pie ? 'slice' : 'bar';
  const nextTag = tags.find(item => !value.some(row => row.tag === item.name));
  const edit = (index, key, next) => onChange(value.map((row, i) => i === index ? { ...row, [key]: next } : row));
  return <fieldset className="chart-fields"><legend>{radar ? 'Radar axes' : pie ? 'Pie slices' : 'Bar series'}</legend>
    {value.map((row, index) => <fieldset key={index}><legend>{rowName[0].toUpperCase() + rowName.slice(1)} {index + 1}</legend>
      <label>Tag<select value={row.tag} onChange={event => edit(index, 'tag', event.target.value)}>
        {!tags.some(tag => tag.name === row.tag) && <option value={row.tag}>{row.tag}</option>}
        {tags.filter(tag => !pie || tag.name === row.tag || !value.some(item => item.tag === tag.name))
          .map(tag => <option key={tag.name} value={tag.name}>{tag.name}</option>)}
      </select></label>
      <label>Series label<input maxLength={100} value={row.label ?? ''} onChange={event => edit(index, 'label', event.target.value)} /></label>
      <label>Decimal places<select value={row.decimals} onChange={event => edit(index, 'decimals', Number(event.target.value))}>
        {decimals.map(value => <option key={value}>{value}</option>)}
      </select></label>
      {radar && <>
        <label>Units<input maxLength={30} value={row.unit ?? ''} onChange={event => edit(index, 'unit', event.target.value)} /></label>
        {['minimum', 'maximum'].map(field => <label key={field}>{field === 'minimum' ? 'Axis minimum' : 'Axis maximum'}
          <input type="number" step="any" value={row[field] ?? ''}
            onChange={event => edit(index, field, Number.isFinite(event.target.valueAsNumber) ? event.target.valueAsNumber : null)} />
        </label>)}
      </>}
      <button type="button" disabled={value.length <= minimum} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove {rowName}</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= maximum || !nextTag}
      onClick={() => onChange([...value, chartSeries(nextTag.name, radar)])}>Add {rowName}</button>
  </fieldset>;
}

export function TankGraphic({ label, position, valid, minimum, maximum, normalLow, normalHigh }) {
  return <div className="tank-graphic">
    <div className={valid ? 'tank-vessel' : 'tank-vessel tank-invalid'} role="img" aria-label={label}>
      {valid && <span className="tank-fill" style={{ height: position + '%' }} data-tank-fill="" aria-hidden="true" />}
      <span className="tank-band" style={{ bottom: normalLow + '%', height: (normalHigh - normalLow) + '%' }} aria-hidden="true" />
    </div>
    <div className="tank-ticks" aria-hidden="true"><span>{maximum}</span><span>{minimum}</span></div>
  </div>;
}

export function GaugeGraphic({ label, position, valid, normalLow, normalHigh }) {
  const point = (percent, radius) => {
    const angle = (150 + 2.4 * percent) * Math.PI / 180;
    return [80 + radius * Math.cos(angle), 78 + radius * Math.sin(angle)];
  };
  const arc = (from, to) => `M${point(from, 60)} A60,60 0 ${to - from > 75 ? 1 : 0} 1 ${point(to, 60)}`;
  const [needleX, needleY] = point(position, 48);
  return <svg className="radial-gauge" role="img" aria-label={label} viewBox="0 0 160 114">
    <path className="gauge-track" d={arc(0, 100)} />
    <path className="gauge-band" d={arc(normalLow, normalHigh)} />
    {[0, 25, 50, 75, 100].map(tick => {
      const [x1, y1] = point(tick, 53), [x2, y2] = point(tick, 57);
      return <line key={tick} className="gauge-tick" x1={x1} y1={y1} x2={x2} y2={y2} />;
    })}
    {valid && <g className="gauge-needle" data-gauge-needle="">
      <line x1="80" y1="78" x2={needleX} y2={needleY} />
      <circle cx="80" cy="78" r="3" />
    </g>}
  </svg>;
}

function readout(value, decimals, language) {
  const options = { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false };
  try { return new Intl.NumberFormat(language, options).format(value); }
  catch { return value.toFixed(decimals); }
}

function RadarPlot({ rows, label }) {
  if (rows.length < 3) return null;
  function point(index, fraction) {
    const angle = index * 2 * Math.PI / rows.length - Math.PI / 2;
    return [120 + 88 * fraction * Math.cos(angle), 120 + 88 * fraction * Math.sin(angle)];
  }
  const profile = rows.map((row, index) => row.valid && row.configured ? point(index, row.position / 100) : null);
  return <svg className="radar-plot" role="img" aria-label={label} viewBox="0 0 240 240">
    {[0.25, 0.5, 0.75, 1].map(fraction => <polygon key={fraction} className="radar-grid"
      points={rows.map((_, index) => point(index, fraction).join(',')).join(' ')} />)}
    {rows.map((_, index) => {
      const [x, y] = point(index, 1), [labelX, labelY] = point(index, 1.2);
      return <g key={index}><line className="radar-grid" x1="120" y1="120" x2={x} y2={y} />
        <text x={labelX} y={labelY} textAnchor="middle" dominantBaseline="middle">{index + 1}</text></g>;
    })}
    {profile.every(Boolean) && <polygon data-radar-profile="" className="radar-profile" points={profile.map(point => point.join(',')).join(' ')} />}
    {profile.map((point, index) => point && <circle key={index} className="radar-dot" cx={point[0]} cy={point[1]} r="3" />)}
  </svg>;
}

const chartColors = ['#364e64', '#694d35', '#3b6055', '#5b4d70', '#765355', '#435965', '#655b36', '#495947'];

function PiePlot({ shares, label }) {
  const point = (fraction, radius) => {
    const angle = (fraction - 0.25) * 2 * Math.PI;
    return [50 + radius * Math.cos(angle), 50 + radius * Math.sin(angle)];
  };
  let edge = 0;
  return <svg className="pie-plot" role="img" aria-label={label} viewBox="0 0 100 100">
    {shares.map((share, index) => {
      if (share === 0) return null;
      const start = edge;
      edge += share;
      const [x, y] = point(start + share / 2, share === 1 ? 0 : 29);
      return <g key={index} data-pie-slice={index + 1} fill={chartColors[index]}>
        {share === 1 ? <circle cx="50" cy="50" r="44" /> : <path d={
          `M50,50 L${point(start, 44)} A44,44 0 ${share > 0.5 ? 1 : 0} 1 ${point(edge, 44)} Z`
        } />}
        {share >= 0.1 && <text x={x} y={y} textAnchor="middle" dominantBaseline="central">{index + 1}</text>}
      </g>;
    })}
  </svg>;
}

export function PieChart({ id, label, series = [], unit, puck }) {
  const live = useContext(Live);
  const { text, ui, language } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const units = text(`control.${id}.unit`, unit);
  const rows = series.map((item, index) => ({
    ...item, ...tagValue(live, item.tag, 'number'),
    label: text(`control.${id}.series.${index}.label`, item.label || item.tag),
  }));
  const complete = rows.length >= 2 && rows.every(row => row.valid && row.value >= 0);
  const peak = complete ? Math.max(...rows.map(row => row.value)) : 0;
  // Scale before summing so finite input values cannot overflow the total.
  const weights = peak > 0 ? rows.map(row => row.value / peak) : [];
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const shares = weights.map(weight => weight / total);
  return <article className="hmi-control hmi-chart" data-control="pie">
    <span className="hmi-label">{title}</span>
    {!shares.length && <small role="status">{ui(complete ? 'pieZero' : 'pieUnavailable')}</small>}
    <div className="chart-plot-content">
      {!!shares.length && <PiePlot shares={shares} label={ui('piePlot', { label: title })} />}
      <ul className="chart-series">
        {rows.map((row, index) => <li key={index} data-chart-tag={row.tag}>
          <div className="chart-row">
            <span><span className="chart-key" style={{ backgroundColor: chartColors[index] }}>{index + 1}</span> {row.label}</span>
            {row.valid ? <strong className="chart-value">{readout(row.value, row.decimals, language.code)} {units}</strong>
              : <Quality problem={row.problem} tag={row.tag} />}
            {shares.length > 0 && <span className="pie-share">{readout(shares[index] * 100, 1, language.code)}%</span>}
          </div>
          {row.valid && row.value < 0 && <strong className="range-deviation">{ui('pieNegative')}</strong>}
          {puck?.isEditing && <span className="hmi-source">{row.tag}</span>}
        </li>)}
      </ul>
    </div>
  </article>;
}

export function XYFields({ value = [], onChange, catalog }) {
  const tags = catalog.tags.filter(tag => tag.type === 'number');
  const update = (index, field, next) => onChange(value.map((row, i) => i === index ? { ...row, [field]: next } : row));
  return <fieldset className="chart-fields"><legend>XY series</legend>
    {value.map((row, index) => <fieldset key={index}><legend>Point {index + 1}</legend>
      {[['x_tag', 'X tag'], ['y_tag', 'Y tag']].map(([field, label]) => <label key={field}>{label}
        <select value={row[field]} onChange={event => update(index, field, event.target.value)}>
          {!tags.some(tag => tag.name === row[field]) && <option value={row[field]}>{row[field]}</option>}
          {tags.map(tag => <option key={tag.name} value={tag.name}>{tag.name}</option>)}
        </select>
      </label>)}
      <label>Series label<input maxLength={100} value={row.label}
        onChange={event => update(index, 'label', event.target.value)} /></label>
      <button type="button" disabled={value.length <= 1} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove point</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= 8 || !tags.length}
      onClick={() => onChange([...value, { x_tag: tags[0].name, y_tag: (tags[1] || tags[0]).name, label: '' }])}>Add point</button>
  </fieldset>;
}

export function XYChart({ id, label, series = [], decimals, x_minimum, x_maximum, x_unit, y_minimum, y_maximum, y_unit }) {
  const live = useContext(Live);
  const { text, ui, language } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const xUnit = text(`control.${id}.x_unit`, x_unit);
  const yUnit = text(`control.${id}.y_unit`, y_unit);
  const scaleOK = validRange(x_minimum, x_maximum) && validRange(y_minimum, y_maximum);
  const rows = series.map((item, index) => {
    const x = tagValue(live, item.x_tag, 'number');
    const y = tagValue(live, item.y_tag, 'number');
    const outside = scaleOK && (x.valid && (x.value < x_minimum || x.value > x_maximum)
      || y.valid && (y.value < y_minimum || y.value > y_maximum));
    return { ...item, x, y, outside, label: text(`control.${id}.series.${index}.label`, item.label || item.x_tag + ' / ' + item.y_tag) };
  });
  const axisScale = (axis, unit, minimum, maximum) => ui('xyAxisScale', {
    axis: unit ? `${axis} (${unit})` : axis, minimum, maximum,
  });
  const reading = (state, tag, unit) => state.valid
    ? <strong className="chart-value">{readout(state.value, decimals, language.code)} {unit}</strong>
    : <Quality problem={state.problem} tag={tag} />;
  return <article className="hmi-control hmi-chart" data-control="xy">
    <span className="hmi-label">{title}</span>
    {!scaleOK && <Quality problem="badRange" />}
    <div className="chart-plot-content">
      {scaleOK && <div className="xy-plot">
        <svg role="img" aria-label={ui('xyPlot', { label: title })} viewBox="0 0 160 124" dir="ltr">
          <path className="xy-grid" d="M50 12V112 M80 12V112 M110 12V112 M20 37H140 M20 62H140 M20 87H140" />
          <rect className="xy-axis" x="20" y="12" width="120" height="100" />
          <text className="xy-axis-label" x="148" y="114">X</text><text className="xy-axis-label" x="8" y="13">Y</text>
          {rows.map((row, index) => {
            if (row.outside || !row.x.valid || !row.y.valid) return null;
            const x = 20 + 1.2 * percentage(row.x.value, x_minimum, x_maximum);
            const y = 112 - percentage(row.y.value, y_minimum, y_maximum);
            return <g key={index} data-xy-point={index + 1}>
              <circle cx={x} cy={y} r="6" fill={chartColors[index]} />
              <text x={x} y={y} textAnchor="middle" dominantBaseline="central">{index + 1}</text>
            </g>;
          })}
        </svg>
        <small>{axisScale('X', xUnit, x_minimum, x_maximum)}</small>
        <small>{axisScale('Y', yUnit, y_minimum, y_maximum)}</small>
      </div>}
      <ul className="chart-series">
        {rows.map((row, index) => <li key={index} data-xy-series={index + 1}>
          <div className="chart-row">
            <span><span className="chart-key" style={{ backgroundColor: chartColors[index] }}>{index + 1}</span> {row.label}</span>
            <span>X {reading(row.x, row.x_tag, xUnit)}</span>
            <span>Y {reading(row.y, row.y_tag, yUnit)}</span>
          </div>
          {row.outside && <strong className="range-deviation">{ui('outOfScale')}</strong>}
        </li>)}
      </ul>
    </div>
  </article>;
}

export function ProcessChart({ id, label, series = [], minimum, maximum, unit, radar, live, puck }) {
  const { text, ui, language } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const scaleOK = radar || validRange(minimum, maximum);
  const rows = series.map((item, index) => {
    const low = radar ? item.minimum : minimum, high = radar ? item.maximum : maximum;
    const { value, valid, problem } = tagValue(live, item.tag, 'number');
    const configured = validRange(low, high);
    const prefix = `control.${id}.series.${index}`;
    return {
      ...item, label: text(prefix + '.label', item.label || item.tag),
      unit: radar ? text(prefix + '.unit', item.unit) : text(`control.${id}.unit`, unit),
      low, high, value, valid, problem, configured, outside: valid && configured && (value < low || value > high),
      position: valid && configured ? percentage(value, low, high) : 0,
    };
  });
  const zero = !radar && scaleOK ? percentage(0, minimum, maximum) : 0;
  const legend = <ul className="chart-series">
    {rows.map((row, index) => <li key={index} data-chart-tag={row.tag}>
      <div className="chart-row"><span>{radar && `${index + 1}. `}{row.label}</span>
        {row.valid ? <strong className="chart-value">{readout(row.value, row.decimals, language.code)} {row.unit}</strong>
          : <Quality problem={row.problem} tag={row.tag} />}
      </div>
      {radar ? <small>{row.configured ? `${row.low} – ${row.high} ${row.unit || ''}` : <Quality problem="badRange" />}</small>
        : scaleOK && <div className={row.valid ? 'bar-track' : 'bar-track chart-invalid'} aria-hidden="true" dir="ltr">
          {row.valid && <span className="bar-fill" data-bar-fill="" style={{
            left: Math.min(zero, row.position) + '%', width: Math.abs(zero - row.position) + '%',
          }} />}
          <span className="bar-zero" style={{ left: zero + '%' }} />
        </div>}
      {row.outside && <strong className="range-deviation">{ui('outOfScale')}</strong>}
      {puck?.isEditing && <span className="hmi-source">{row.tag}</span>}
    </li>)}
  </ul>;
  return <article className="hmi-control hmi-chart" data-control={radar ? 'radar' : 'bar'}>
    <span className="hmi-label">{title}</span>
    {!scaleOK && <Quality problem="badRange" />}
    {radar ? <div className="chart-plot-content"><RadarPlot rows={rows} label={title} />{legend}</div> : legend}
    {!radar && scaleOK && <div className="analog-scale" dir="ltr">
      <span>{minimum}</span><span>{text(`control.${id}.unit`, unit)}</span><span>{maximum}</span>
    </div>}
  </article>;
}
