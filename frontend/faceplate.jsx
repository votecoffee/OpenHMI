import React, { useContext } from 'react';
import { Live } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import { controlTypes } from './model.mjs';
import { resolveFaceplateControl } from './faceplate-model.mjs';

export function FaceplateInstance({ id, label, template, root_tag, puck, config, enabled_tag }) {
  const live = useContext(Live);
  const { text } = useLocalization();
  const definition = live.project?.faceplates?.find(item => item.id === template);
  if (!definition) return <article className="hmi-control" data-control="faceplate"><strong>{label}</strong><p>Faceplate definition unavailable</p></article>;
  return <article className="hmi-faceplate" data-control="faceplate"><strong>{text(`control.${id}.label`, label)}</strong><div className="faceplate-grid">{definition.controls.map(control => {
    const resolved = resolveFaceplateControl(control, { id, root_tag, puck, enabled_tag });
    return <React.Fragment key={control.id}>{config.components[controlTypes[control.kind]].render(resolved)}</React.Fragment>;
  })}</div></article>;
}
