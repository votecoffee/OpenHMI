import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useUi } from './localization.jsx';
import './touch-entry.css';

export function Popup({ title, close, children }) {
  const ui = useUi();
  const dialog = useRef();
  useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
  return createPortal(<dialog ref={dialog} aria-label={title} className="hmi-popup" onCancel={event => { event.preventDefault(); close(); }}><header><h2>{title}</h2><button type="button" onClick={close} aria-label={ui('closeDialog', { title })}>×</button></header>{children}</dialog>, document.body);
}

export function TouchEntry({ title, initial = '', numeric = false, secret = false, limits, close, accept }) {
  const ui = useUi();
  const [entry, setEntry] = useState(initial), [shift, setShift] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      if (numeric && (!entry.trim() || !Number.isFinite(Number(entry)))) throw new Error(ui('invalidNumericEntry'));
      const value = numeric ? Number(entry) : entry;
      const measured = numeric ? value : Array.from(entry).length;
      if (limits && (!limits.valid || measured < limits.low || measured > limits.high)) {
        throw new Error(limits.valid ? ui(numeric ? 'allowedNumericRange' : 'allowedTextLength', limits) : ui('editLimitsUnavailable'));
      }
      await accept(value); close();
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }
  const rows = numeric ? ['789', '456', '123', '-0.'] : shift ? ['~!@#$%^&*()_+', 'QWERTYUIOP{}|', 'ASDFGHJKL:"', 'ZXCVBNM<>?'] : ['`1234567890-=', 'qwertyuiop[]\\', "asdfghjkl;'", 'zxcvbnm,./'];
  const entryLabel = ui(secret ? 'passwordEntry' : 'entryLabel');
  return <Popup title={title} close={close}><form onSubmit={submit}>
    <label>{entryLabel}<input autoFocus type={secret ? 'password' : 'text'} inputMode={numeric ? 'decimal' : 'text'} autoComplete="off" value={entry} onChange={event => setEntry(event.target.value)} /></label>
    {limits && <p>{limits.valid ? ui(numeric ? 'numericRange' : 'textLength', limits) : ui('editLimitsUnavailable')}</p>}
    <fieldset disabled={busy} className={`touch-keys ${numeric ? 'numeric-keys' : ''}`}><legend>{ui(numeric ? 'numericKeypad' : 'textKeyboard')}</legend>
      {rows.map((row, index) => <div className="key-row" key={index}>{Array.from(row).map(key => <button type="button" key={key} onClick={() => setEntry(entry + key)}>{key}</button>)}</div>)}
      <div className="key-row">{!numeric && <><button type="button" aria-pressed={shift} onClick={() => setShift(!shift)}>{ui('shiftKey')}</button><button type="button" onClick={() => setEntry(entry + ' ')}>{ui('spaceKey')}</button></>}
        <button type="button" onClick={() => setEntry(Array.from(entry).slice(0, -1).join(''))}>{ui('backspaceKey')}</button><button type="button" onClick={() => setEntry('')}>{ui('clearEntry')}</button></div>
    </fieldset><p role="alert">{error}</p><footer><button type="button" disabled={busy} onClick={close}>{ui('cancelEntry')}</button><button disabled={busy}>{ui('acceptEntry')}</button></footer>
  </form></Popup>;
}
