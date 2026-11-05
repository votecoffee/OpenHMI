import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './touch-entry.css';

export function Popup({ title, close, children }) {
  const dialog = useRef();
  useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
  return createPortal(<dialog ref={dialog} aria-label={title} className="hmi-popup" onCancel={event => { event.preventDefault(); close(); }}><header><h2>{title}</h2><button type="button" onClick={close} aria-label={`Close ${title}`}>×</button></header>{children}</dialog>, document.body);
}

export function TouchEntry({ title, initial = '', numeric = false, secret = false, limits, close, accept }) {
  const [entry, setEntry] = useState(initial), [shift, setShift] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      if (numeric && (!entry.trim() || !Number.isFinite(Number(entry)))) throw new Error('Enter a finite number');
      const value = numeric ? Number(entry) : entry;
      const measured = numeric ? value : Array.from(entry).length;
      if (limits && (!limits.valid || measured < limits.low || measured > limits.high)) throw new Error(limits.valid ? `Allowed ${numeric ? 'range' : 'length'}: ${limits.low} to ${limits.high}` : 'Edit limits unavailable');
      await accept(value); close();
    } catch (problem) { setError(problem.message); }
    finally { setBusy(false); }
  }
  const rows = numeric ? ['789', '456', '123', '-0.'] : shift ? ['~!@#$%^&*()_+', 'QWERTYUIOP{}|', 'ASDFGHJKL:"', 'ZXCVBNM<>?'] : ['`1234567890-=', 'qwertyuiop[]\\', "asdfghjkl;'", 'zxcvbnm,./'];
  return <Popup title={title} close={close}><form onSubmit={submit}>
    <label>{secret ? 'Password entry' : 'Entry'}<input autoFocus aria-label={secret ? 'Password entry' : 'Entry'} type={secret ? 'password' : 'text'} inputMode={numeric ? 'decimal' : 'text'} autoComplete="off" value={entry} onChange={event => setEntry(event.target.value)} /></label>
    {limits && <p>{limits.valid ? `${numeric ? 'Range' : 'Length'}: ${limits.low} – ${limits.high}` : 'Edit limits unavailable'}</p>}
    <fieldset disabled={busy} className={`touch-keys ${numeric ? 'numeric-keys' : ''}`}><legend>{numeric ? 'Numeric keypad' : 'Text keyboard'}</legend>
      {rows.map((row, index) => <div className="key-row" key={index}>{Array.from(row).map(key => <button type="button" key={key} onClick={() => setEntry(entry + key)}>{key}</button>)}</div>)}
      <div className="key-row">{!numeric && <><button type="button" aria-pressed={shift} onClick={() => setShift(!shift)}>Shift</button><button type="button" onClick={() => setEntry(entry + ' ')}>Space</button></>}
        <button type="button" onClick={() => setEntry(Array.from(entry).slice(0, -1).join(''))}>Backspace</button><button type="button" onClick={() => setEntry('')}>Clear</button></div>
    </fieldset><p role="alert">{error}</p><footer><button type="button" disabled={busy} onClick={close}>Cancel</button><button disabled={busy}>Accept entry</button></footer>
  </form></Popup>;
}
