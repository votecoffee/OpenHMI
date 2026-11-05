import React, { useEffect, useId, useMemo, useState } from 'react';
import { api } from './api.mjs';
import { useLocalization } from './localization.jsx';
import './trend.css';

const colors = ['#002878', '#803e00', '#11615b', '#563684', '#39522b', '#8a3350'];
const dashes = [undefined, '9 4', '2 3', '12 3 2 3'];
const gridTimes = [0, 150, 300, 450, 600];
const isFixed = settings => settings.minimum != null || settings.maximum != null;
const isAnalog = value => typeof value === 'number' && Number.isFinite(value);

export function TrendFields({ value = { tags: ['TankLevel'], series: {} }, onChange, catalog }) {
  const { tags, series } = value;
  const available = catalog.tags.filter(tag => ['number', 'boolean'].includes(tag.type) && !tags.includes(tag.name));
  function update(tag, changes) {
    onChange({ tags, series: { ...series, [tag]: { ...series[tag], ...changes } } });
  }
  function remove(tag) {
    const next = { ...series };
    delete next[tag];
    onChange({ tags: tags.filter(name => name !== tag), series: next });
  }
  return <fieldset className="trend-fields"><legend>Trend tags</legend>
    {[...new Set(tags)].map(tag => {
      const settings = series[tag] || {};
      const digital = catalog.tags.find(item => item.name === tag)?.type === 'boolean';
      const fixed = isFixed(settings);
      return <fieldset key={tag}><legend>{tag}</legend>
        {digital ? <span>Boolean lane</span> : <>
          <label>Decimal places<select aria-label={tag + ' decimal places'} value={settings.decimals ?? 1}
            onChange={event => update(tag, { decimals: Number(event.target.value) })}>
            {Array.from({ length: 9 }, (_, index) => <option key={index}>{index}</option>)}
          </select></label>
          <label>Y-axis range<select aria-label={tag + ' Y-axis range'} value={fixed ? 'fixed' : 'auto'}
            onChange={event => update(tag, event.target.value === 'fixed' ? { minimum: 0, maximum: 100 } : { minimum: null, maximum: null })}>
            <option value="auto">Observed min/max</option><option value="fixed">Fixed</option>
          </select></label>
          {fixed && ['minimum', 'maximum'].map(field => <label key={field}>{field === 'minimum' ? 'Minimum' : 'Maximum'}
            <input type="number" step="any" aria-label={tag + ' ' + field} value={settings[field] ?? ''}
              onChange={event => update(tag, { [field]: Number.isFinite(event.target.valueAsNumber) ? event.target.valueAsNumber : null })} />
          </label>)}
        </>}
        <button type="button" aria-label={'Remove ' + tag} onClick={() => remove(tag)}>Remove tag</button>
      </fieldset>;
    })}
    <label>Add tag<select aria-label="Add trend tag" value="" disabled={tags.length >= 12 || !available.length}
      onChange={event => { if (event.target.value) onChange({ tags: [...tags, event.target.value], series }); }}>
      <option value="">Choose numeric or Boolean tag</option>
      {available.map(tag => <option key={tag.name} value={tag.name}>{tag.name} ({tag.type})</option>)}
    </select></label>
    {!tags.length && <small>Select at least one tag.</small>}
  </fieldset>;
}

function scale(settings, samples) {
  if (isFixed(settings)) {
    const { minimum, maximum } = settings;
    return Number.isFinite(minimum) && Number.isFinite(maximum) && Number.isFinite(maximum - minimum) && maximum > minimum
      ? [minimum, maximum] : null;
  }
  const values = samples.filter(row => row.quality === 'good' && isAnalog(row.value)).map(row => row.value);
  return values.length ? [Math.min(...values), Math.max(...values)] : null;
}

function yPosition(value, [minimum, maximum]) {
  if (minimum === maximum) return 80;
  const span = maximum - minimum;
  const fraction = Number.isFinite(span) ? (value - minimum) / span
    : (value / 2 - minimum / 2) / (maximum / 2 - minimum / 2);
  // Keep far-off-scale vertices within the SVG renderer's coordinate limits.
  return 160 * (1 - Math.max(-100000, Math.min(100000, fraction)));
}

function Trace({ series, start, seconds }) {
  const segments = [];
  let points = null;
  for (const row of series.samples) {
    if (row.quality !== 'good' || !(series.digital ? typeof row.value === 'boolean' : isAnalog(row.value))) {
      points = null;
      continue;
    }
    const x = 600 * (row.epoch - start) / seconds;
    const y = series.digital ? (row.value ? 5 : 23) : yPosition(row.value, series.range);
    if (!points) {
      points = [];
      segments.push(points);
    }
    if (series.digital && points.length) points.push([x, points.at(-1)[1]]);
    points.push([x, y]);
  }
  return <g data-trend-tag={series.tag}>{segments.map((points, index) => points.length === 1
    ? <circle key={index} cx={points[0][0]} cy={points[0][1]} r="2" fill={series.color} />
    : <polyline key={index} points={points.map(point => point.join(',')).join(' ')} fill="none"
      stroke={series.color} strokeDasharray={series.dash} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />)}</g>;
}

function Plot({ analog, digital, start, seconds, historical, label }) {
  const clipId = useId();
  return <div className="trend-plot" dir="ltr">
    {analog.length > 0 && <div className="trend-plot-row">
      <span>Analog</span>
      <svg role="img" aria-label={label + ' trend'} viewBox="0 0 600 160" preserveAspectRatio="none">
        <defs><clipPath id={clipId}><rect width="600" height="160" /></clipPath></defs>
        <path className="trend-grid" d="M0 40H600 M0 80H600 M0 120H600" />
        {gridTimes.map(x => <path key={x} className="trend-grid" d={`M${x} 0V160`} />)}
        <g clipPath={`url(#${clipId})`}>{analog.filter(item => item.range).map(item => <Trace key={item.binding} series={item} start={start} seconds={seconds} />)}</g>
      </svg>
    </div>}
    {digital.map(item => <div className="trend-plot-row trend-lane" key={item.binding} data-trend-lane={item.tag}>
      <span title={item.tag}>{item.tag}</span>
      <svg role="img" aria-label={item.tag + ' Boolean history'} viewBox="0 0 600 28" preserveAspectRatio="none">
        <path className="trend-grid" d="M0 5H600 M0 23H600" />
        {gridTimes.map(x => <path key={x} className="trend-grid" d={`M${x} 0V28`} />)}
        <Trace series={item} start={start} seconds={seconds} />
      </svg>
    </div>)}
    <div className="trend-plot-row"><span>Time</span><div className="trend-time"><span>{'-' + seconds + ' s'}</span><span>{historical ? 'End' : 'Now'}</span></div></div>
  </div>;
}

function formatTime(seconds) {
  if (seconds % 3600 === 0) return seconds / 3600 + ' h';
  if (seconds % 60 === 0) return seconds / 60 + ' min';
  return seconds + ' s';
}

export function Trend({ id, label, pens, tags = ['TankLevel'], series: settings, seconds = 300, puck, live, catalog }) {
  const { text, ui, language } = useLocalization();
  label = text(`control.${id}.label`, label);
  const [response, setResponse] = useState(null);
  const [windowSeconds, setWindowSeconds] = useState(seconds);
  const [endTime, setEndTime] = useState('');
  useEffect(() => setWindowSeconds(seconds), [seconds]);

  const root = pens?.root || live.previewRoot;
  const seriesTags = [...new Set(pens?.tags ?? tags)];
  const resolve = tag => tag.startsWith('$.') ? (root ? root + tag.slice(1) : '') : tag;
  const names = [...new Set(seriesTags.map(resolve).filter(Boolean))].join(',');
  const end = endTime ? Date.parse(endTime) / 1000 : null;
  const query = names && windowSeconds > 0 && (end === null || Number.isFinite(end))
    ? new URLSearchParams({ tags: names, seconds: windowSeconds, ...(end === null ? {} : { end }) }).toString() : '';
  useEffect(() => {
    if (!query) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const data = await api('/api/history?' + query);
        if (!stopped) setResponse({ query, data });
      } catch {
        if (!stopped) setResponse({ query, error: true });
      }
      if (!stopped && end === null) timer = setTimeout(refresh, 1000);
    }
    refresh();
    return () => { stopped = true; clearTimeout(timer); };
  }, [query, end]);

  const history = response?.query === query ? response.data : null;
  const error = response?.query === query && response.error;
  const samplesByTag = useMemo(() => {
    const result = new Map();
    for (const row of history?.samples ?? []) {
      if (!result.has(row.tag)) result.set(row.tag, []);
      result.get(row.tag).push(row);
    }
    return result;
  }, [history]);
  const plotted = seriesTags.map((tag, index) => {
    const name = resolve(tag);
    const config = (pens?.series ?? settings)?.[tag] ?? {};
    const current = Object.hasOwn(live.values, name) ? live.values[name] : undefined;
    const samples = samplesByTag.get(name) ?? [];
    const kind = catalog.tags.find(item => item.name === tag || item.name === name)?.type;
    const digital = kind === 'boolean' || !kind && (typeof current === 'boolean' ||
      typeof samples.findLast(row => row.quality === 'good')?.value === 'boolean');
    const range = digital ? null : scale(config, samples);
    return { binding: tag, tag: name || tag, digital, range, fixed: isFixed(config), current, samples, decimals: config.decimals ?? 1,
      color: colors[index % colors.length], dash: digital ? undefined : dashes[index % dashes.length] };
  });
  const analog = plotted.filter(item => !item.digital);
  const digital = plotted.filter(item => item.digital);
  const hasSamples = plotted.some(item => item.samples.some(row => row.quality === 'good'
    && (item.digital ? typeof row.value === 'boolean' : isAnalog(row.value))));
  function formatValue(value, decimals) {
    const options = { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false };
    try { return new Intl.NumberFormat(language.code, options).format(value); }
    catch { return value.toFixed(decimals); }
  }

  return <article className="hmi-control hmi-trend" data-control="trend">
    <span className="hmi-label">{label}</span>
    {!puck?.isEditing && <div className="trend-tools">
      <label>Time range<select aria-label={label + ' time range'} value={windowSeconds}
        onChange={event => setWindowSeconds(Number(event.target.value))}>
        {[...new Set([seconds, 60, 300, 900, 3600, 86400])].sort((a, b) => a - b).map(value => <option key={value} value={value}>{formatTime(value)}</option>)}
      </select></label>
      <label>End time<input aria-label={label + ' history end'} type="datetime-local" value={endTime}
        onChange={event => setEndTime(event.target.value)} /></label>
      <button type="button" onClick={() => setEndTime('')}>Live</button>
    </div>}
    {plotted.length > 0 && <Plot analog={analog} digital={digital} start={history?.start ?? 0}
      seconds={history ? history.end - history.start : windowSeconds} historical={!!endTime} label={label} />}
    {plotted.length > 0 && <table className="trend-legend"><thead><tr><th>Tag</th><th>Current (live)</th><th>Y-axis range</th></tr></thead>
      <tbody>{plotted.map(item => <tr key={item.binding} data-trend-value={item.tag}>
        <th scope="row"><svg width="24" height="10" aria-hidden="true"><path d="M0 5H24" stroke={item.color} strokeWidth="2" strokeDasharray={item.dash} /></svg>{item.tag}</th>
        <td>{!live.connected ? ui('commLoss')
          : item.digital && typeof item.current === 'boolean' ? ui(item.current ? 'on' : 'off')
            : !item.digital && isAnalog(item.current) ? formatValue(item.current, item.decimals) : ui('badData')}</td>
        <td>{item.digital ? '0 / 1'
          : item.range ? <>{item.range.join(' to ')} <small>{item.fixed ? 'Fixed' : 'Observed'}</small></>
            : item.fixed ? 'Invalid range' : 'Waiting for samples'}</td>
      </tr>)}</tbody>
    </table>}
    {error ? <span className="hmi-quality">{ui('badData')} - history unavailable</span>
      : !plotted.length ? <p>Select trend tags.</p>
        : history && !hasSamples ? <p>No recorded good samples in this window. Check History settings and tag quality.</p> : null}
    {history?.truncated && <p>Result limited; shorten the time range.</p>}
    {!puck?.isEditing && query && <a href={'/api/history.csv?' + query}>Export history CSV</a>}
  </article>;
}
