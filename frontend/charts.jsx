import React from 'react';
import { tagValue, Quality } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import './charts.css';

const validRange = (minimum, maximum) => Number.isFinite(minimum) && Number.isFinite(maximum)
  && Number.isFinite(maximum - minimum) && maximum > minimum;
const percentage = (value, minimum, maximum) => 100 * ((Math.min(maximum, Math.max(minimum, value)) - minimum) / (maximum - minimum));
const decimals = [0, 1, 2, 3, 4];

export function chartSeries(tag, radar) {
  return { tag, label: '', decimals: 1, ...(radar ? { unit: '', minimum: 0, maximum: 100 } : {}) };
}

export function ChartFields({ value = [], onChange, catalog, radar }) {
  const tags = catalog.tags.filter(tag => tag.type === 'number');
  const minimum = radar ? 3 : 1, maximum = radar ? 8 : 12;
  const nextTag = tags.find(item => !value.some(row => row.tag === item.name));
  const edit = (index, key, next) => onChange(value.map((row, i) => i === index ? { ...row, [key]: next } : row));
  return <fieldset className="chart-fields"><legend>{radar ? 'Radar axes' : 'Bar series'}</legend>
    {value.map((row, index) => <fieldset key={index}><legend>{radar ? 'Axis' : 'Bar'} {index + 1}</legend>
      <label>Tag<select value={row.tag} onChange={event => edit(index, 'tag', event.target.value)}>
        {!tags.some(tag => tag.name === row.tag) && <option value={row.tag}>{row.tag}</option>}
        {tags.map(tag => <option key={tag.name} value={tag.name}>{tag.name}</option>)}
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
      <button type="button" disabled={value.length <= minimum} onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove {radar ? 'axis' : 'bar'}</button>
    </fieldset>)}
    <button type="button" disabled={value.length >= maximum || !nextTag}
      onClick={() => onChange([...value, chartSeries(nextTag.name, radar)])}>Add {radar ? 'axis' : 'bar'}</button>
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
    {radar ? <div className="radar-content"><RadarPlot rows={rows} label={title} />{legend}</div> : legend}
    {!radar && scaleOK && <div className="analog-scale" dir="ltr">
      <span>{minimum}</span><span>{text(`control.${id}.unit`, unit)}</span><span>{maximum}</span>
    </div>}
  </article>;
}
