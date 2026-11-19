import React from 'react';
import { useValue, Quality } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { formatUtcEpoch } from './edit-control.jsx';
import { TagReference, formatNumeric } from './control-common.jsx';

const ledSegments = ['M4 3h8', 'M13 4v7', 'M13 14v7', 'M4 22h8', 'M3 14v7', 'M3 4v7', 'M4 12.5h8'];
const ledGlyphs = {
  '0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg',
  '5': 'acdfg', '6': 'acdefg', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg', '-': 'g',
};

export function LedDisplay({ id, label, tag, unit, digits, decimals, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const units = text(`control.${id}.unit`, unit);
  const configured = Number.isInteger(digits) && digits >= 2 && digits <= 12
    && Number.isInteger(decimals) && decimals >= 0 && decimals <= 4 && decimals < digits;
  const rounded = valid && configured ? value.toFixed(decimals) : '';
  const reading = rounded.startsWith('-') && Number(rounded) === 0 ? rounded.slice(1) : rounded;
  const glyphs = reading.replace('.', '');
  const overflow = valid && (/[eE]/.test(reading) || glyphs.length > digits);
  const dotAfter = reading.includes('.') ? digits - decimals - 1 : -1;
  return <article className="hmi-control hmi-led" data-control="led_display">
    <span className="hmi-label">{title}</span>
    {!configured ? <Quality problem="badRange" /> : !valid ? <Quality problem={problem} tag={tag} /> : overflow ? <>
      <strong className="range-deviation">{ui('ledOverflow')}</strong><small>{value} {units}</small>
    </> : <div className="led-reading">
      <svg role="img" aria-label={[title, reading, units].filter(Boolean).join(' ')}
        viewBox={`0 0 ${digits * 18} 26`} width={digits * 18} height="26">
        {Array.from(glyphs.padStart(digits)).map((glyph, index) => {
          const lit = ledGlyphs[glyph] || '';
          return <g key={index} transform={`translate(${index * 18} 0)`}>
            {ledSegments.map((path, segment) => <path key={path} d={path}
              className={lit.includes('abcdefg'[segment]) ? 'led-lit' : 'led-unlit'} />)}
            {index === dotAfter && <circle className="led-dot" cx="16.5" cy="22" r="1.4" />}
          </g>;
        })}
      </svg>
      {units && <small aria-hidden="true">{units}</small>}
    </div>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

export function TagQuality({ id, label, tag, show_age, puck }) {
  const { problem } = useValue(tag);
  const { text } = useLocalization();
  return <article className="hmi-control" data-control="tag_quality">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <Quality problem={problem || 'tagGood'} tag={tag} showAge={show_age} />
    <TagReference tag={tag} puck={puck} />
  </article>;
}

export function NumericDisplay({ id, label, tag, unit, decimals, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, language } = useLocalization();
  const formatted = valid ? formatNumeric(value, decimals, language.code) : '';
  return <article className="hmi-control hmi-numeric" data-control="numeric">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-value">{formatted} <small>{text(`control.${id}.unit`, unit)}</small></strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

export const annotationSymbols = {
  arrow: { label: 'Arrow', path: 'M4 12h15m-6-6 6 6-6 6' },
  info: { label: 'Information', path: 'M12 11v6m0-10v.2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z' },
  warning: { label: 'Warning', path: 'M12 3 22 21H2zm0 7v4m0 3v.2' },
  check: { label: 'Check mark', path: 'm4 12 5 5L20 6' },
  circle: { label: 'Circle', path: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z' },
  diamond: { label: 'Diamond', path: 'm12 2 10 10-10 10L2 12z' },
};

export function StaticLabel({ id, label, font_size, alignment, weight }) {
  const { text } = useLocalization();
  return <div className="hmi-annotation hmi-static-label" data-control="label"
    style={{ fontSize: font_size, textAlign: alignment, fontWeight: weight }}>
    {text(`control.${id}.label`, label)}
  </div>;
}

export function ScreenSymbol({ id, label, symbol, size, rotation }) {
  const { text } = useLocalization();
  return <div className="hmi-annotation hmi-symbol" data-control="symbol">
    <svg role="img" aria-label={text(`control.${id}.label`, label)} viewBox="0 0 24 24" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={annotationSymbols[symbol]?.path} transform={`rotate(${rotation} 12 12)`} />
    </svg>
  </div>;
}

export function ProgressBar({ id, label, tag, unit, decimals, minimum, maximum, puck }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui } = useLocalization();
  const title = text(`control.${id}.label`, label);
  const reading = valid ? `${value.toFixed(decimals)} ${text(`control.${id}.unit`, unit)}`.trim() : '';
  const span = maximum - minimum;
  const outside = valid && (value < minimum || value > maximum);
  return <article className="hmi-control hmi-progress" data-control="progress">
    <span className="hmi-label">{title}</span>
    {valid ? <strong className="hmi-value">{reading}</strong> : <Quality problem={problem} tag={tag} />}
    {!(0 < span && Number.isFinite(span)) ? <Quality problem="badRange" /> : valid && <>
      <progress aria-label={title} aria-valuetext={reading} max={1}
        value={Math.max(0, Math.min(1, (value - minimum) / span))} />
      <div className="analog-scale"><span>{minimum}</span>
        {outside && <strong>{ui('outOfScale')}</strong>}<span>{maximum}</span></div>
    </>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

function formatDuration(value, sourceUnit, decimals) {
  const scale = 10 ** decimals;
  const ticks = Math.round(value * (sourceUnit === 'milliseconds' ? scale / 1000 : scale));
  if (value < 0 || !Number.isSafeInteger(ticks)) return '';
  const fraction = ticks % scale;
  const whole = (ticks - fraction) / scale;
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole / 60) % 60;
  const clock = [hours, minutes, whole % 60].map(part => String(part).padStart(2, '0')).join(':');
  return decimals ? clock + '.' + String(fraction).padStart(decimals, '0') : clock;
}

export function TimeDisplay({ id, label, tag, puck, source_unit, decimals = 0, duration = false }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui } = useLocalization();
  const reading = valid ? (duration ? formatDuration(value, source_unit, decimals) : formatUtcEpoch(value)) : '';
  return <article className="hmi-control hmi-time-display" data-control={duration ? 'duration' : 'date_time_display'}>
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {!valid ? <Quality problem={problem} tag={tag} /> : reading ? <strong className="hmi-value">{reading}</strong>
      : <strong className="range-deviation">{ui(duration ? 'durationInvalid' : 'dateTimeInvalid')}</strong>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

export function TextDisplay({ id, label, tag, puck }) {
  const { value, valid, problem } = useValue(tag, 'string');
  const { text } = useLocalization();
  return <article className="hmi-control" data-control="text">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className="hmi-text-value">{value}</strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}

export function Indicator({ id, label, tag, on_text = 'ON', off_text = 'OFF', puck }) {
  const { value, valid, problem } = useValue(tag, 'boolean');
  const { text } = useLocalization();
  return <article className="hmi-control hmi-indicator" data-control="indicator">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    {valid ? <strong className={`hmi-state ${value ? 'is-on' : ''}`}>
      <span className="binary-symbol" aria-hidden="true" />{value ? text(`control.${id}.on_text`, on_text) : text(`control.${id}.off_text`, off_text)}
    </strong> : <Quality problem={problem} tag={tag} />}
    <TagReference tag={tag} puck={puck} />
  </article>;
}
