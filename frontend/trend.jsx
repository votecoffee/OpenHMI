import React, { useEffect, useId, useMemo, useState } from 'react';
import { api } from './api.mjs';
import { useLocalization } from './localization.jsx';
import './trend.css';
import { CaptureTools, useTrendCaptures } from './trend-recording.jsx';

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
  let minimum = Infinity, maximum = -Infinity;
  for (const row of samples) {
    if (!goodSample(row, false)) continue;
    minimum = Math.min(minimum, row.value);
    maximum = Math.max(maximum, row.value);
  }
  return minimum === Infinity ? null : [minimum, maximum];
}

function yPosition(value, [minimum, maximum]) {
  if (minimum === maximum) return 80;
  const span = maximum - minimum;
  const fraction = Number.isFinite(span) ? (value - minimum) / span
    : (value / 2 - minimum / 2) / (maximum / 2 - minimum / 2);
  // Keep far-off-scale vertices within the SVG renderer's coordinate limits.
  return 160 * (1 - Math.max(-100000, Math.min(100000, fraction)));
}

function goodSample(row, digital) {
  return row?.quality === 'good' && (digital ? typeof row.value === 'boolean' : isAnalog(row.value));
}

function holdChangeSamples(samples, context, start, end) {
  const rows = context.previous && samples[0]?.epoch !== start ? [context.previous, ...samples] : samples;
  const points = [];
  rows.forEach((row, index) => {
    if (row.epoch >= start) points.push(row);
    if (row.quality !== 'good') return;
    const from = Math.max(start, row.epoch);
    const next = rows[index + 1]?.epoch ?? end;
    const until = Math.min(next, row.epoch + context.hold_seconds);
    if (until < from) return;
    if (row.epoch < start) points.push({ ...row, epoch: from });
    if (until > from) points.push({ ...row, epoch: until });
    if (until < next) points.push({ epoch: until, quality: 'stale' });
  });
  return points;
}

function cursorValue({ samples, digital }, epoch) {
  let first = 0, last = samples.length;
  while (first < last) {
    const middle = Math.floor((first + last) / 2);
    if (samples[middle].epoch <= epoch) first = middle + 1;
    else last = middle;
  }
  const before = samples[first - 1], after = samples[first];
  if (!goodSample(before, digital)) return undefined;
  if (before.epoch === epoch) return before.value;
  if (!goodSample(after, digital)) return undefined;
  if (digital) return before.value;
  const fraction = (epoch - before.epoch) / (after.epoch - before.epoch);
  return before.value * (1 - fraction) + after.value * fraction;
}

const Trace = React.memo(function Trace({ series, start, seconds }) {
  const segments = [];
  let points = null;
  for (const row of series.samples) {
    if (!goodSample(row, series.digital)) {
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
}, (previous, next) => {
  const before = previous.series, after = next.series;
  return previous.start === next.start && previous.seconds === next.seconds && before.samples === after.samples
    && before.tag === after.tag && before.digital === after.digital && before.color === after.color
    && before.dash === after.dash && before.range?.[0] === after.range?.[0] && before.range?.[1] === after.range?.[1];
});

function TrendPlot({ analog, digital, start, seconds, historical, label, cursor, pinned, setCursor, hasHistory }) {
  const clipId = useId();
  function inspect(fraction, pinned) {
    const position = Math.max(0, Math.min(1, fraction));
    if (!pinned) setCursor({ fraction: position });
    else if (hasHistory) setCursor({ epoch: start + position * seconds });
  }
  function point(event) {
    if (!event.isPrimary || pinned && event.pointerType === 'mouse' && event.type === 'pointermove') return;
    const matrix = event.currentTarget.getScreenCTM();
    if (!matrix) return;
    const location = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    if (Number.isFinite(location.x)) inspect(location.x / 600, event.pointerType !== 'mouse');
  }
  function key(event) {
    if (event.key === 'Escape' && cursor !== null) { event.preventDefault(); setCursor(null); return; }
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    inspect((cursor ?? 0.5) + (event.key === 'ArrowLeft' ? -0.01 : 0.01), true);
  }
  const pointer = { onPointerMove: point, onPointerDown: point };
  const line = height => cursor != null && <line className="trend-cursor" data-trend-cursor=""
    x1={cursor * 600} x2={cursor * 600} y1="0" y2={height} vectorEffect="non-scaling-stroke" />;
  return <div className="trend-plot" dir="ltr" tabIndex={0} aria-label={label + ' timeline. Use left and right arrows to move the cursor.'}
    onPointerLeave={event => {
      if (event.pointerType === 'mouse') setCursor(previous => previous?.epoch === undefined ? null : previous);
    }} onKeyDown={key}>
    {analog.length > 0 && <div className="trend-plot-row">
      <span>Analog</span>
      <svg role="img" aria-label={label + ' trend'} viewBox="0 0 600 160" preserveAspectRatio="none" {...pointer}>
        <defs><clipPath id={clipId}><rect width="600" height="160" /></clipPath></defs>
        <path className="trend-grid" d="M0 40H600 M0 80H600 M0 120H600" />
        {gridTimes.map(x => <path key={x} className="trend-grid" d={`M${x} 0V160`} />)}
        <g clipPath={`url(#${clipId})`}>{analog.filter(item => item.range).map(item => <Trace key={item.binding} series={item} start={start} seconds={seconds} />)}</g>
        {line(160)}
      </svg>
    </div>}
    {digital.map(item => <div className="trend-plot-row trend-lane" key={item.binding} data-trend-lane={item.tag}>
      <span title={item.tag}>{item.tag}</span>
      <svg role="img" aria-label={item.tag + ' Boolean history'} viewBox="0 0 600 28" preserveAspectRatio="none" {...pointer}>
        <path className="trend-grid" d="M0 5H600 M0 23H600" />
        {gridTimes.map(x => <path key={x} className="trend-grid" d={`M${x} 0V28`} />)}
        <Trace series={item} start={start} seconds={seconds} />
        {line(28)}
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

export function Trend({ id, label, pens, tags = ['TankLevel'], series: settings, seconds = 300, recording, puck, live, catalog }) {
  const { text, ui, language } = useLocalization();
  label = text(`control.${id}.label`, label);
  const [response, setResponse] = useState(null);
  const [windowSeconds, setWindowSeconds] = useState(seconds);
  const [windowInput, setWindowInput] = useState(String(seconds));
  const [endTime, setEndTime] = useState(null);
  const [cursor, setCursor] = useState(null);
  const captures = useTrendCaptures(id, puck?.isEditing, !!recording);
  const capture = captures.capture;
  useEffect(() => { setWindowSeconds(seconds); setWindowInput(String(seconds)); }, [seconds]);
  useEffect(() => { setEndTime(null); }, [capture?.id]);
  useEffect(() => { setCursor(null); }, [capture?.id, windowSeconds, endTime]);

  const root = pens?.root || live.previewRoot;
  const seriesTags = [...new Set(pens?.tags ?? tags)];
  const resolve = tag => tag.startsWith('$.') ? (root ? root + tag.slice(1) : '') : tag;
  const names = [...new Set(seriesTags.map(resolve).filter(Boolean))].join(',');
  const follow = endTime === null && (!capture || capture.stopped === null);
  const parameters = new URLSearchParams({ seconds: windowSeconds, ...(endTime === null ? {} : { end: endTime }) });
  if (!capture) parameters.set('tags', names);
  const query = capture ? `/api/trend-captures/${capture.id}?${parameters}` : names ? `/api/history?${parameters}&trend_context=true` : '';
  useEffect(() => {
    if (!query) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const data = await api(query);
        if (!stopped) setResponse({ query, data });
      } catch {
        if (!stopped) setResponse({ query, error: true });
      }
      if (!stopped && follow) timer = setTimeout(refresh, 1000);
    }
    refresh();
    return () => { stopped = true; clearTimeout(timer); };
  }, [query, follow]);

  const history = response?.query === query ? response.data : null;
  const error = response?.query === query && response.error;
  const samplesByTag = useMemo(() => {
    const result = new Map();
    for (const row of history?.samples ?? []) {
      if (!result.has(row.tag)) result.set(row.tag, []);
      result.get(row.tag).push(row);
    }
    for (const [tag, context] of Object.entries(history?.change_context ?? {})) {
      result.set(tag, holdChangeSamples(result.get(tag) ?? [], context, history.start, history.end));
    }
    return result;
  }, [history]);
  const bindings = capture?.series ?? seriesTags.map(tag => ({ binding: tag, tag: resolve(tag) || tag,
    ...(pens?.series ?? settings)?.[tag] }));
  const plotted = bindings.map((config, index) => {
    const name = config.tag;
    const tag = config.binding ?? name;
    const current = Object.hasOwn(live.values, name) ? live.values[name] : undefined;
    const samples = samplesByTag.get(name) ?? [];
    const kind = config.type ?? catalog.tags.find(item => item.name === tag || item.name === name)?.type;
    const digital = kind === 'boolean' || !kind && (typeof current === 'boolean' ||
      typeof samples.findLast(row => row.quality === 'good')?.value === 'boolean');
    const range = digital ? null : scale(config, samples);
    return { binding: tag, tag: name || tag, digital, range, fixed: isFixed(config), current, samples, decimals: config.decimals ?? 1,
      color: colors[index % colors.length], dash: digital ? undefined : dashes[index % dashes.length] };
  });
  const analog = plotted.filter(item => !item.digital);
  const digital = plotted.filter(item => item.digital);
  const hasSamples = plotted.some(item => item.samples.some(row => goodSample(row, item.digital)));
  const span = history ? history.end - history.start : 0;
  const position = history && cursor?.epoch !== undefined ? (cursor.epoch - history.start) / span : cursor?.fraction;
  const cursorFraction = position >= 0 && position <= 1 ? position : null;
  const cursorEpoch = cursorFraction === null || !history ? null : cursor.epoch ?? history.start + cursorFraction * span;
  const cursorDate = cursorEpoch === null ? null : new Date(cursorEpoch * 1000);
  const cursorTime = cursorDate?.toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
  });
  const shownEnd = endTime === null ? null : new Date(endTime * 1000);
  const localEnd = shownEnd ? new Date(shownEnd.getTime() - shownEnd.getTimezoneOffset() * 60000).toISOString().slice(0, 19) : '';
  function changeWindow(value) {
    setWindowSeconds(value);
    setWindowInput(String(value));
  }
  function applyWindow() {
    const value = Number(windowInput);
    if (Number.isInteger(value) && value >= 1 && value <= 604800) changeWindow(value);
    else setWindowInput(String(windowSeconds));
  }
  function formatValue(value, decimals) {
    const options = { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false };
    try { return new Intl.NumberFormat(language.code, options).format(value); }
    catch { return value.toFixed(decimals); }
  }

  return <article className="hmi-control hmi-trend" data-control="trend">
    <span className="hmi-label">{label}</span>
    {!puck?.isEditing && <div className="trend-tools">
      <label>Time range<select aria-label={label + ' time range'} value={windowSeconds}
        onChange={event => changeWindow(Number(event.target.value))}>
        {[...new Set([windowSeconds, seconds, 10, 30, 60, 300, 900, 3600, 86400])].sort((a, b) => a - b).map(value => <option key={value} value={value}>{formatTime(value)}</option>)}
      </select></label>
      <label>Window (seconds)<input aria-label={label + ' window seconds'} type="number" min="1" max="604800"
        value={windowInput} onChange={event => setWindowInput(event.target.value)} onBlur={applyWindow}
        onKeyDown={event => { if (event.key === 'Enter') applyWindow(); }} /></label>
      <label>End time<input aria-label={label + ' history end'} type="datetime-local" step="1" value={localEnd}
        onChange={event => {
          const epoch = Date.parse(event.target.value) / 1000;
          setEndTime(Number.isFinite(epoch) && epoch >= 0 && epoch <= 32503680000 ? epoch : null);
        }} /></label>
      <button type="button" onClick={() => setEndTime(null)}>{capture?.stopped != null ? 'Latest' : 'Live'}</button>
    </div>}
    {!puck?.isEditing && <CaptureTools state={captures} recording={recording} endTime={endTime} setEndTime={setEndTime} />}
    {plotted.length > 0 && <TrendPlot analog={analog} digital={digital} start={history?.start ?? 0}
      seconds={history ? history.end - history.start : windowSeconds} historical={!follow} label={label}
      cursor={cursorFraction} pinned={cursorFraction !== null && cursor?.epoch !== undefined}
      setCursor={setCursor} hasHistory={!!history} />}
    {cursorDate && <div className="trend-cursor-readout"><span className="trend-cursor-time" data-trend-cursor-time="">
      Cursor: {cursorDate.toLocaleDateString()} {cursorTime}
    </span>{cursor.epoch !== undefined && <button type="button" onClick={() => setCursor(null)}>{ui('clearTrendCursor')}</button>}</div>}
    {plotted.length > 0 && <table className="trend-legend"><thead><tr><th>Tag</th><th>Current (live)</th>
      <th>At cursor</th><th>Y-axis range</th></tr></thead>
      <tbody>{plotted.map(item => {
        const atCursor = cursorEpoch == null ? undefined : cursorValue(item, cursorEpoch);
        return <tr key={item.binding} data-trend-value={item.tag}>
        <th scope="row"><svg width="24" height="10" aria-hidden="true"><path d="M0 5H24" stroke={item.color} strokeWidth="2" strokeDasharray={item.dash} /></svg>{item.tag}</th>
        <td>{!live.connected ? ui('commLoss')
          : item.digital && typeof item.current === 'boolean' ? ui(item.current ? 'on' : 'off')
            : !item.digital && isAnalog(item.current) ? formatValue(item.current, item.decimals) : ui('badData')}</td>
        <td data-trend-cursor-value="">{atCursor === undefined ? '—' : item.digital ? ui(atCursor ? 'on' : 'off') : formatValue(atCursor, item.decimals)}</td>
        <td>{item.digital ? '0 / 1'
          : item.range ? <>{item.range.join(' to ')} <small>{item.fixed ? 'Fixed' : 'Observed'}</small></>
            : item.fixed ? 'Invalid range' : 'Waiting for samples'}</td>
      </tr>; })}</tbody>
    </table>}
    {error ? <span className="hmi-quality">{ui('badData')} - history unavailable</span>
      : !plotted.length ? <p>Select trend tags.</p>
        : history && !hasSamples ? <p>No recorded good samples in this window. Check acquisition settings and tag quality.</p> : null}
    {history?.truncated && <p>Result limited; shorten the time range.</p>}
    {Object.keys(history?.change_context ?? {}).length > 0 && <small>On-change traces hold the last recorded value between samples.</small>}
    {!puck?.isEditing && !capture && query && <a href={'/api/history.csv?' + parameters}>Export history CSV</a>}
  </article>;
}
