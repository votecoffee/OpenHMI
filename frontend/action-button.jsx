import React, { useContext, useEffect, useState } from 'react';
import { Live, tagValue, Quality } from './live-quality.jsx';
import { api } from './api.mjs';
import { activateControl } from './runtime-api.mjs';
import { isCommandPage, isCommandRecord } from './command-status.mjs';
import { SecurityContext, allowed, SecurityLock } from './security.jsx';
import { useLocalization } from './localization.jsx';

export function ActionButton({ id, label, action, mode = 'python', command = '', target = '', security_groups = [], puck, enabled_tag = '' }) {
  const live = useContext(Live);
  const { session } = useContext(SecurityContext) || {};
  const definition = mode === 'command' ? live.project?.commands?.find(item => item.id === command) : null;
  const permitted = allowed(session, 'runtime.operate', security_groups) && (mode !== 'command' || !!definition && allowed(session, 'runtime.operate', definition.security_groups));
  const { text, ui } = useLocalization();
  const targetTag = mode === 'command' ? definition?.root_tag : ['set', 'toggle'].includes(mode) ? target : '';
  const permitTag = definition?.permit_member ? definition.root_tag + '.' + definition.permit_member : '';
  const enabled = enabled_tag ? tagValue(live, enabled_tag, 'boolean') : null;
  const permit = permitTag ? tagValue(live, permitTag, 'boolean') : null;
  const targetState = targetTag ? tagValue(live, targetTag, mode === 'toggle' ? 'boolean' : undefined) : null;
  const unavailableBinding = [
    { state: enabled, tag: enabled_tag, label: 'editEnableBinding' },
    { state: permit, tag: permitTag, label: 'actionPermitBinding' },
    { state: targetState, tag: targetTag, label: mode === 'command' ? 'actionCommandBinding' : 'actionTargetBinding' },
  ].find(binding => binding.state?.problem);
  const unavailable = !live.connected ? 'commLoss' : unavailableBinding?.state.problem;
  const unavailableLabel = unavailableBinding ? ui('editBindingProblem', {
    binding: ui(unavailableBinding.label), quality: ui(unavailable),
  }) : undefined;
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [failed, setFailed] = useState(false);
  const [latest, setCommandStatus] = useState(null);
  const commandStatus = latest?.command === command ? latest : null;
  const transaction = commandStatus?.transaction;
  const commandBlocked = mode === 'command' && (!commandStatus?.available
    || ['prepared', 'staging', 'requested', 'accepted', 'uncertain'].includes(transaction?.state));
  useEffect(() => {
    if (mode !== 'command' || puck?.isEditing || !permitted) { setCommandStatus(null); return; }
    if (busy) return;
    let stopped = false, timer;
    async function refresh() {
      try {
        const data = await api(`/api/commands?command_id=${encodeURIComponent(command)}&limit=1`);
        if (!isCommandPage(data) || data.items.length > 1 || data.items.some(item => item.command_id !== command)) {
          throw new Error('Invalid command status response');
        }
        const next = data.items[0] ?? null;
        if (!stopped) setCommandStatus(previous => {
          const known = previous?.command === command ? previous.transaction : null;
          return known && (!next || known.id > next.id)
            ? { command, available: false, transaction: known }
            : { command, available: true, transaction: next };
        });
      } catch (error) {
        const denied = [401, 403].includes(error.status);
        if (!stopped) setCommandStatus(previous => ({ command, available: false,
          transaction: !denied && previous?.command === command ? previous.transaction : null }));
      }
      if (!stopped) timer = setTimeout(refresh, 1000);
    }
    refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [command, mode, permitted, puck?.isEditing, busy]);
  async function invoke(event) {
    const opener = event.currentTarget;
    setBusy(true);
    setFailed(false);
    try {
      const result = await activateControl(id, live.activeRevision);
      if (mode === 'command') {
        if (!isCommandRecord(result?.transaction) || result.transaction.command_id !== command) {
          throw new Error(ui('commandStatusUnavailable'));
        }
        setCommandStatus({ command, available: null, transaction: result.transaction });
      }
      if (result.mode) window.dispatchEvent(new CustomEvent('openhmi-navigate', { detail: { ...result, opener } }));
      setFeedback(result.transaction ? `Request dispatched. Transaction ${result.transaction.id}${result.audit_status === 'pending' ? `; activity finalization pending. Operation ${result.operation_id}` : ''}` : result.audit_status === 'pending' ? `Completed; activity finalization pending. Operation ${result.operation_id}` : ui('completed'));
    } catch (error) {
      if (mode === 'command') setCommandStatus(previous => ({ command, available: false,
        transaction: ![401, 403].includes(error.status) && previous?.command === command ? previous.transaction : null }));
      setFeedback(error.message); setFailed(true);
    } finally { setBusy(false); }
  }
  return <article className="hmi-control hmi-command security-protected" data-control="button">
    <button className="hmi-action" disabled={puck?.isEditing || !!unavailable || busy || !permitted || !!enabled && enabled.value !== true || !!permit && permit.value !== true || commandBlocked} onClick={invoke}>
      {busy ? ui('working') : text(`control.${id}.label`, label)}
    </button><span className={failed ? 'hmi-quality' : 'command-feedback'}>
      {busy ? ui('pending') : puck?.isEditing ? ui('configureAction') : feedback || (!permitted ? 'Sign in with an authorized HMI group' : '')}
    </span>
    {unavailable && !puck?.isEditing && <Quality problem={unavailable} tag={unavailableBinding?.tag} text={unavailableLabel} />}
    {!puck?.isEditing && enabled?.valid && enabled.value === false && <small>{ui('editEnableOff', { tag: enabled_tag })}</small>}
    {!puck?.isEditing && permit?.valid && permit.value === false && <small>{ui('actionPermitOff', { tag: permitTag })}</small>}
    {!permitted && !puck?.isEditing && <SecurityLock label={label} permission="runtime.operate" groups={security_groups} additionalGroups={definition?.security_groups || []} />}
    {mode === 'command' && permitted && !puck?.isEditing && !busy && !commandStatus?.available &&
      <span className="hmi-quality" role="status">{ui(commandStatus?.available === false ? 'commandStatusUnavailable' : 'commandStatusWaiting')}</span>}
    {mode === 'command' && permitted && !puck?.isEditing && transaction && <>
      <span className="command-feedback" role="status">PLC command: {transaction.state} · sequence {transaction.sequence}{transaction.result_code !== null ? ` · result ${transaction.result_code}` : ''}</span>
      <a className="command-transaction-link" href={`/commands?transaction=${transaction.id}`}>{ui('viewCommandTransaction', { id: transaction.id })}</a>
    </>}
  </article>;
}
