import React, { useContext } from 'react';
import { Live, tagValue, Quality } from './live-quality.jsx';
import { useUi } from './localization.jsx';

export function Conditional({ children, visible_tag, enabled_tag, color_tag, active_color, puck }) {
  const live = useContext(Live);
  const ui = useUi();
  const isTrue = tag => { const state = tagValue(live, tag, 'boolean'); return state.valid && state.value; };
  if (!puck?.isEditing && visible_tag && !isTrue(visible_tag)) return null;
  const enabled = !puck?.isEditing && enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const disabled = enabled != null && (!enabled.valid || enabled.value !== true);
  return <div className="binding-frame" style={color_tag && isTrue(color_tag) ? { '--hmi-live': active_color, '--hmi-annotation-color': active_color } : {}}>
    {disabled && (enabled.valid ? <small>{ui('editEnableOff', { tag: enabled_tag })}</small>
      : <Quality tag={enabled_tag} problem={enabled.problem}
        text={ui('editBindingProblem', { binding: ui('editEnableBinding'), quality: ui(enabled.problem) })} />)}
    <fieldset className="binding-contents" disabled={disabled}>{children}</fieldset>
  </div>;
}
