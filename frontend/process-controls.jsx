import React from 'react';
import { useValue, Quality } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { TagReference, formatNumeric } from './control-common.jsx';
import { GaugeGraphic, TankGraphic } from './charts.jsx';

export function SetpointComparison({ id, label, tag, setpoint_tag, tolerance, tolerance_tag, unit, decimals }) {
  const process = useValue(tag, 'number');
  const setpoint = useValue(setpoint_tag, 'number');
  const limit = useValue(tolerance_tag, 'number');
  const { text, ui, language } = useLocalization();
  const units = text(`control.${id}.unit`, unit);
  const threshold = tolerance_tag ? limit.value : tolerance;
  const limitOK = (!tolerance_tag || limit.valid) && Number.isFinite(threshold) && threshold >= 0;
  const deviation = process.valid && setpoint.valid ? process.value - setpoint.value : NaN;
  const hasDeviation = Number.isFinite(deviation);
  // Allow for floating-point subtraction at the tolerance boundary.
  const roundoff = threshold > 0 && hasDeviation
    ? Number.EPSILON * Math.max(Math.abs(process.value), Math.abs(setpoint.value), threshold) : 0;
  const outside = hasDeviation && limitOK && Math.abs(deviation) - threshold > roundoff;
  const reading = (value, signed = false) => `${formatNumeric(value, decimals, language.code, signed)} ${units}`.trim();
  return <article className="hmi-control" data-control="setpoint_comparison">
    <span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <dl className="setpoint-readings">
      <dt>{ui('comparisonProcess')}</dt><dd>{process.valid ? reading(process.value) : <Quality problem={process.problem} tag={tag} />}</dd>
      <dt>{ui('comparisonSetpoint')}</dt><dd>{!setpoint_tag ? ui('comparisonChooseSetpoint')
        : setpoint.valid ? reading(setpoint.value) : <Quality problem={setpoint.problem} tag={setpoint_tag} />}</dd>
      <dt>{ui('comparisonDeviation')}</dt><dd>{hasDeviation ? reading(deviation, true) : '—'}</dd>
      <dt>{ui('comparisonTolerance')}</dt><dd>{limitOK ? reading(threshold) : tolerance_tag && !limit.valid
        ? <Quality problem={limit.problem} tag={tolerance_tag} /> : <Quality problem="badRange" />}</dd>
    </dl>
    <strong className={outside ? 'range-deviation' : undefined}>
      {ui(!hasDeviation || !limitOK ? 'comparisonUnavailable' : outside ? 'comparisonOutside' : 'comparisonWithin')}
    </strong>
  </article>;
}

export function AnalogRange({ id, label, tag, unit, decimals, minimum, maximum, normal_low, normal_high, puck, kind = 'analog' }) {
  const { value, valid, problem } = useValue(tag, 'number');
  const { text, ui, language } = useLocalization();
  label = text(`control.${id}.label`, label);
  unit = text(`control.${id}.unit`, unit);
  const formatted = valid ? formatNumeric(value, decimals, language.code) : '';
  const configured = [minimum, maximum, normal_low, normal_high].every(Number.isFinite)
    && Number.isFinite(maximum - minimum) && minimum <= normal_low && normal_low < normal_high && normal_high <= maximum;
  const position = number => Math.max(0, Math.min(100, (number - minimum) / (maximum - minimum) * 100));
  const outside = valid && (value < minimum || value > maximum);
  const graphicLabel = valid ? `${label}: ${value} ${unit}, scale ${minimum} to ${maximum}, normal ${normal_low} to ${normal_high}${outside ? ', out of scale' : ''}` : `${label}: ${ui(problem)}`;
  const Graphic = kind === 'gauge' ? GaugeGraphic : kind === 'tank' ? TankGraphic : null;
  return <article className="hmi-control hmi-analog" data-control={kind}>
    <div className="analog-heading"><span className="hmi-label">{label}</span>
      {valid ? <strong className="hmi-value">{formatted} <small>{unit}</small></strong> : <Quality problem={problem} tag={tag} />}</div>
    {!configured ? <Quality problem="badRange" /> : <>
      {Graphic ? <Graphic label={graphicLabel} position={valid ? position(value) : 0} valid={valid} minimum={minimum} maximum={maximum}
        normalLow={position(normal_low)} normalHigh={position(normal_high)} />
        : <div className={`analog-track ${!valid ? 'invalid' : ''}`} role="img" aria-label={graphicLabel}>
        <span className="normal-band" style={{ left: `${position(normal_low)}%`, width: `${position(normal_high) - position(normal_low)}%` }} />
        {valid && <span className="analog-pointer" style={{ left: `${position(value)}%` }} aria-hidden="true">▼</span>}
      </div>}
      <div className="analog-scale">{kind !== 'tank' && <span>{minimum}</span>}<span>{ui('normal')} {normal_low}–{normal_high} {unit}</span>{kind !== 'tank' && <span>{maximum}</span>}</div>
      {valid && (outside || value < normal_low || value > normal_high) && <strong className="range-deviation">{outside ? ui('outOfScale') : ui('outsideBand')}</strong>}
    </>}
    <TagReference tag={tag} puck={puck} />
  </article>;
}
