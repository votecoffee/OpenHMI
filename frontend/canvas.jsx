import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.mjs';
import './canvas.css';

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const id = () => 'canvas-' + crypto.randomUUID();
const maxX = box => box.x + box.width;
const maxY = box => box.y + box.height;
const settings = (layout, key, value) => ({ ...layout, [key]: value });

function size(type) {
  if (type === 'Trend') return { width: 480, height: 320 };
  if (['TankLevel', 'BarGraph', 'RadarChart', 'Faceplate'].includes(type)) return { width: 240, height: 240 };
  return { width: 176, height: 80 };
}

export function initialCanvas(data) {
  const columns = data.root.props.columns || 2;
  const width = Math.max(1024, columns * 340);
  const boxes = {};
  let y = 8;
  for (let start = 0; start < data.content.length; start += columns) {
    const row = data.content.slice(start, start + columns);
    const rowHeight = Math.max(...row.map(item => size(item.type).height));
    row.forEach((item, index) => {
      const box = size(item.type);
      boxes[item.props.id] = { ...box, width: Math.min(box.width, Math.floor(width / columns) - 16),
        x: 8 + Math.floor(index * width / columns), y, z: start + index, group: '' };
    });
    y += rowHeight + 8;
  }
  const height = Math.max(640, Math.min(4096, y));
  for (const box of Object.values(boxes)) box.y = Math.min(box.y, height - box.height);
  return { width, height, grid: 8, snap: true, background: '', boxes, containers: {} };
}

function bounds(boxes) {
  const x = Math.min(...boxes.map(box => box.x)), y = Math.min(...boxes.map(box => box.y));
  return { x, y, width: Math.max(...boxes.map(maxX)) - x, height: Math.max(...boxes.map(maxY)) - y };
}

const memberIDs = layout => new Set(Object.values(layout.containers).flatMap(container => container.members));
const objectEntries = layout => [...Object.entries(layout.boxes), ...Object.entries(layout.containers)];
const topObjects = layout => {
  const members = memberIDs(layout);
  return objectEntries(layout).filter(([key]) => !members.has(key)).sort((a, b) => a[1].z - b[1].z);
};
const boxStyle = box => ({ left: box.x, top: box.y, width: box.width, height: box.height, zIndex: box.z + 1 });

function renderBlock(config, item, editing) {
  const component = config.components[item.type];
  return component?.render({ ...component.defaultProps, ...item.props, puck: { isEditing: editing } });
}

export function CanvasSurface({ data, config, editor }) {
  const { layout } = data.root.props;
  const content = new Map(data.content.map(item => [item.props.id, item]));
  const editing = !!editor;
  return <div className="canvas-scroll">
    <div ref={editor?.surface} className={`hmi-canvas${editing && layout.snap ? ' canvas-grid' : ''}`} dir="ltr"
      aria-label={editing ? 'Freeform canvas' : 'Freeform screen'}
      style={{ width: layout.width, height: layout.height, '--canvas-grid': layout.grid + 'px', zoom: editor?.zoom || 1 }}
      onClick={event => { if (event.target === event.currentTarget) editor?.select([]); }}
      onDragOver={editing ? event => event.preventDefault() : undefined}
      onDrop={editor?.drop}>
      {layout.background && <img className="canvas-background" src={'/api/canvas-images/' + layout.background} alt="" draggable={false} />}
      {topObjects(layout).map(([key, box]) => {
        const container = layout.containers[key], item = content.get(key);
        const selection = editor?.selected.includes(key);
        const label = item?.props.label || (container?.mode === 'grid' ? 'Grid container' : 'Scrollable stack');
        return <div key={key} data-canvas-object={key} className={`canvas-object${selection ? ' canvas-selected' : ''}`} style={boxStyle(box)}>
          <div className="canvas-object-body" inert={editing || undefined}>
            {container ? <div className={`canvas-container canvas-container-${container.mode}`}
              style={{ '--container-columns': container.columns }}>
              {container.members.map(member => content.has(member) && <div key={member} className="canvas-member">
                {renderBlock(config, content.get(member), editing)}
              </div>)}
            </div> : item && renderBlock(config, item, editing)}
          </div>
          {editing && <>
            <button type="button" aria-label={'Select and move ' + label} aria-pressed={selection}
              className="canvas-move" onPointerDown={event => editor.begin(event, key)}
              onClick={event => { if (event.detail === 0) editor.selectObject(key, event.shiftKey); }} />
            {selection && <button type="button" aria-label={'Resize ' + label} className="canvas-resize"
              onPointerDown={event => editor.begin(event, key, true)} />}
          </>}
        </div>;
      })}
    </div>
  </div>;
}

function NumberField({ label, value, min, max, change }) {
  const [draft, setDraft] = useState(null);
  function commit(event) {
    const next = event.currentTarget.valueAsNumber;
    if (Number.isInteger(next) && next !== value) change(clamp(next, min, max));
    setDraft(null);
  }
  return <label>{label}<input type="number" aria-label={label} min={min} max={max} value={draft ?? value}
    onChange={event => setDraft(event.target.value)} onBlur={commit}
    onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }} /></label>;
}

function Properties({ item, component, onChange }) {
  if (!item || !component) return null;
  return <fieldset><legend>Control properties</legend>{Object.entries(component.fields).map(([key, field]) => {
    const value = item.props[key] ?? component.defaultProps[key];
    const change = next => onChange(key, next);
    if (field.type === 'custom') return <div key={key}>{field.render({ field, name: key, value, onChange: change })}</div>;
    return <label key={key}>{field.label || key}{field.type === 'select'
      ? <select value={field.options.findIndex(option => option.value === value)}
          onChange={event => change(field.options[Number(event.target.value)]?.value ?? '')}>
        <option value={-1}>Choose...</option>
        {field.options.map((option, index) => <option key={index} value={index}>{option.label}</option>)}
      </select>
      : <input type={field.type} value={value ?? ''} min={field.min} max={field.max} step={field.type === 'number' ? 'any' : undefined}
        onChange={event => change(field.type === 'number' ? event.target.valueAsNumber : event.target.value)} />}
    </label>;
  })}</fieldset>;
}

export function CanvasEditor({ data, config, onChange, canEdit }) {
  const { layout } = data.root.props;
  const [selected, select] = useState([]);
  const [palette, setPalette] = useState(Object.keys(config.components)[0]);
  const [zoom, setZoom] = useState(1);
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState('');
  const surface = useRef(null);
  const pendingImage = useRef(0);
  const latest = useRef({ data, onChange });
  latest.current = { data, onChange };
  useEffect(() => () => { pendingImage.current += 1; }, []);
  const members = memberIDs(layout);
  const item = selected.length === 1 ? data.content.find(entry => entry.props.id === selected[0]) : null;
  const selectedContainer = selected.length === 1 ? layout.containers[selected[0]] : null;
  const object = selected.length === 1 ? layout.boxes[selected[0]] || selectedContainer : null;
  const freeSelection = selected.filter(key => !members.has(key) && (layout.boxes[key] || layout.containers[key]));
  const top = topObjects(layout);
  const objects = Object.fromEntries(objectEntries(layout));

  function change(next, content = data.content) {
    onChange({ root: { props: { ...data.root.props, layout: next } }, content });
  }

  function boxesChanged(changes, original = layout) {
    const next = { ...original, boxes: { ...original.boxes }, containers: { ...original.containers } };
    for (const [key, patch] of Object.entries(changes)) {
      const map = next.boxes[key] ? next.boxes : next.containers;
      map[key] = { ...map[key], ...patch };
    }
    return next;
  }

  function selectionFor(key, extend) {
    const box = objects[key];
    const group = box?.group && !members.has(key) ? top.filter(([, member]) => member.group === box.group).map(([name]) => name) : [key];
    if (!extend) return group;
    return group.every(name => selected.includes(name)) ? selected.filter(name => !group.includes(name)) : [...new Set([...selected, ...group])];
  }

  function add(type, position = { x: 8, y: 8 }) {
    const component = config.components[type];
    if (!canEdit || !component || data.content.length >= 100) return;
    const key = id(), box = size(type);
    const snap = value => layout.snap ? Math.round(value / layout.grid) * layout.grid : Math.round(value);
    const next = { ...layout, boxes: { ...layout.boxes, [key]: { ...box,
      width: Math.min(box.width, layout.width), height: Math.min(box.height, layout.height),
      x: clamp(snap(position.x), 0, Math.max(0, layout.width - box.width)),
      y: clamp(snap(position.y), 0, Math.max(0, layout.height - box.height)), z: top.length, group: '',
    } } };
    change(next, [...data.content, { type, props: { ...component.defaultProps, id: key } }]);
    select([key]);
  }

  function begin(event, key, resize = false) {
    if (!canEdit || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const keys = resize ? [key] : event.shiftKey ? selectionFor(key, true)
      : selected.includes(key) ? freeSelection : selectionFor(key, false);
    select(keys);
    if (!keys.includes(key)) return;
    const anchor = objects[key];
    const area = bounds(keys.map(name => objects[name]));
    const element = event.currentTarget;
    const startX = event.clientX, startY = event.clientY;
    const snap = value => layout.snap ? Math.round(value / layout.grid) * layout.grid : Math.round(value);
    let next, moved = false;
    element.setPointerCapture(event.pointerId);
    function move(pointer) {
      const dx = (pointer.clientX - startX) / zoom, dy = (pointer.clientY - startY) / zoom;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      moved = true;
      if (resize) {
        next = boxesChanged({ [key]: {
          width: clamp(snap(anchor.width + dx), 32, layout.width - anchor.x),
          height: clamp(snap(anchor.height + dy), 24, layout.height - anchor.y),
        } });
      } else {
        const x = clamp(snap(anchor.x + dx) - anchor.x, -area.x, layout.width - maxX(area));
        const y = clamp(snap(anchor.y + dy) - anchor.y, -area.y, layout.height - maxY(area));
        next = boxesChanged(Object.fromEntries(keys.map(name => [name, { x: objects[name].x + x, y: objects[name].y + y }])));
      }
      setPreview(next);
    }
    function finish(pointer) {
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerup', finish);
      element.removeEventListener('pointercancel', finish);
      element.removeEventListener('lostpointercapture', finish);
      setPreview(null);
      if (pointer.type === 'pointerup' && next) change(next);
    }
    element.addEventListener('pointermove', move);
    element.addEventListener('pointerup', finish);
    element.addEventListener('pointercancel', finish);
    element.addEventListener('lostpointercapture', finish);
  }

  function reorder(front) {
    const chosen = top.filter(([key]) => freeSelection.includes(key));
    const other = top.filter(([key]) => !freeSelection.includes(key));
    change(boxesChanged(Object.fromEntries((front ? [...other, ...chosen] : [...chosen, ...other]).map(([key], z) => [key, { z }]))));
  }

  function align(axis, edge) {
    const dimension = axis === 'x' ? 'width' : 'height';
    const area = bounds(freeSelection.map(key => objects[key]));
    change(boxesChanged(Object.fromEntries(freeSelection.map(key => [key, {
      [axis]: area[axis] + Math.round((area[dimension] - objects[key][dimension]) * edge),
    }]))));
  }

  function distribute(axis) {
    const dimension = axis === 'x' ? 'width' : 'height';
    const keys = [...freeSelection].sort((a, b) => objects[a][axis] - objects[b][axis]);
    const area = bounds(keys.map(key => objects[key]));
    const space = (area[dimension] - keys.reduce((total, key) => total + objects[key][dimension], 0)) / (keys.length - 1);
    let position = area[axis];
    const changes = {};
    for (const key of keys) {
      changes[key] = { [axis]: clamp(Math.round(position), area[axis], area[axis] + area[dimension] - objects[key][dimension]) };
      position += objects[key][dimension] + space;
    }
    change(boxesChanged(changes));
  }

  function pack(mode) {
    const key = id(), area = bounds(freeSelection.map(name => objects[name]));
    const container = { ...area, mode, columns: 2, members: [...freeSelection], z: top.length, group: '' };
    const next = boxesChanged(Object.fromEntries(freeSelection.map(name => [name, { group: '' }])));
    change({ ...next, containers: { ...next.containers, [key]: container } });
    select([key]);
  }

  function remove() {
    const next = { ...layout, boxes: { ...layout.boxes }, containers: { ...layout.containers } };
    for (const key of selected) { delete next.boxes[key]; delete next.containers[key]; }
    for (const [key, container] of Object.entries(next.containers)) {
      next.containers[key] = { ...container, members: container.members.filter(member => !selected.includes(member)) };
    }
    change(next, data.content.filter(block => !selected.includes(block.props.id)));
    select([]);
  }

  async function background(file) {
    if (!file || !canEdit) return;
    const request = ++pendingImage.current;
    try {
      setMessage('Uploading image...');
      const image = await api('/api/canvas-images', { method: 'POST', body: file, signal: AbortSignal.timeout(15000) });
      if (request !== pendingImage.current) return;
      const current = latest.current.data;
      latest.current.onChange({ ...current, root: { props: { ...current.root.props,
        layout: settings(current.root.props.layout, 'background', image.id) } } });
      setMessage('');
    } catch (error) { if (request === pendingImage.current) setMessage(error.message); }
  }

  function drop(event) {
    event.preventDefault();
    const rect = surface.current.getBoundingClientRect();
    add(event.dataTransfer.getData('application/x-openhmi-control'), { x: (event.clientX - rect.left) / zoom, y: (event.clientY - rect.top) / zoom });
  }

  const canvasData = preview ? { ...data, root: { props: { ...data.root.props, layout: preview } } } : data;
  const canPack = freeSelection.length > 0 && freeSelection.every(key => layout.boxes[key]) && Object.keys(layout.containers).length < 30;
  const minWidth = Math.max(160, ...Object.values(objects).map(maxX));
  const minHeight = Math.max(120, ...Object.values(objects).map(maxY));
  return <section className="canvas-editor" aria-label="Freeform designer">
    <fieldset className="canvas-toolbar" disabled={!canEdit}><legend>Canvas tools</legend>
      <label>Screen name<input value={data.root.props.title} maxLength={120}
        onChange={event => onChange({ ...data, root: { props: { ...data.root.props, title: event.target.value } } })} /></label>
      <NumberField label="Canvas width" value={layout.width} min={minWidth} max={4096} change={value => change(settings(layout, 'width', value))} />
      <NumberField label="Canvas height" value={layout.height} min={minHeight} max={4096} change={value => change(settings(layout, 'height', value))} />
      <label><input type="checkbox" checked={layout.snap} onChange={event => change(settings(layout, 'snap', event.target.checked))} />Snap to grid</label>
      <NumberField label="Grid spacing" value={layout.grid} min={2} max={100} change={value => change(settings(layout, 'grid', value))} />
      <label>Zoom<select value={zoom} onChange={event => setZoom(Number(event.target.value))}>
        {[0.5, 0.75, 1, 1.25].map(value => <option key={value} value={value}>{value * 100}%</option>)}
      </select></label>
      <label>Background image<input type="file" accept="image/png,image/jpeg,image/webp"
        onChange={event => { background(event.target.files[0]); event.target.value = ''; }} /></label>
      {layout.background && <button type="button" onClick={() => change(settings(layout, 'background', ''))}>Clear background</button>}
    </fieldset>
    {message && <p role="status">{message}</p>}
    <div className="canvas-workbench">
      <aside className="canvas-tools">
        <fieldset disabled={!canEdit}><legend>Control palette</legend>
          <label>Control type<select value={palette} onChange={event => setPalette(event.target.value)}>
            {Object.entries(config.components).map(([type, component]) => <option key={type} value={type}>{component.label || type}</option>)}
          </select></label>
          <button type="button" draggable={canEdit} onDragStart={event => event.dataTransfer.setData('application/x-openhmi-control', palette)}
            onClick={() => add(palette)} disabled={data.content.length >= 100}>Add or drag control</button>
        </fieldset>
        <fieldset><legend>Objects</legend>
          {top.map(([key, box]) => <React.Fragment key={key}>
            <button type="button" aria-pressed={selected.includes(key)} onClick={event => select(selectionFor(key, event.shiftKey))}>
              {data.content.find(block => block.props.id === key)?.props.label || (box.mode === 'grid' ? 'Grid container' : 'Scrollable stack')}
            </button>
            {box.members?.map(member => <button type="button" className="canvas-outline-member" key={member}
              aria-pressed={selected.includes(member)} onClick={() => select([member])}>{data.content.find(block => block.props.id === member)?.props.label}</button>)}
          </React.Fragment>)}
        </fieldset>
      </aside>
      <CanvasSurface data={canvasData} config={config}
        editor={{ selected, select, selectObject: (key, extend) => select(selectionFor(key, extend)), begin, drop, surface, zoom }} />
      <aside className="canvas-tools">
        <fieldset disabled={!canEdit}><legend>Selection</legend>
          <small>Shift-click to select multiple objects.</small>
          <button type="button" disabled={!freeSelection.length} onClick={() => reorder(true)}>Bring to front</button>
          <button type="button" disabled={!freeSelection.length} onClick={() => reorder(false)}>Send to back</button>
          <button type="button" disabled={freeSelection.length < 2} onClick={() => {
            const group = id();
            change(boxesChanged(Object.fromEntries(freeSelection.map(key => [key, { group }]))));
          }}>Group</button>
          <button type="button" disabled={!freeSelection.some(key => objects[key].group)}
            onClick={() => change(boxesChanged(Object.fromEntries(freeSelection.map(key => [key, { group: '' }]))))}>Ungroup</button>
          {[['x', ['Align left', 'Align horizontal centers', 'Align right']], ['y', ['Align top', 'Align vertical centers', 'Align bottom']]]
            .flatMap(([axis, labels]) => labels.map((label, index) => <button key={label} type="button"
              disabled={freeSelection.length < 2} onClick={() => align(axis, index / 2)}>{label}</button>))}
          <button type="button" disabled={freeSelection.length < 3} onClick={() => distribute('x')}>Space horizontally</button>
          <button type="button" disabled={freeSelection.length < 3} onClick={() => distribute('y')}>Space vertically</button>
          <button type="button" disabled={!canPack} onClick={() => pack('grid')}>Pack into grid</button>
          <button type="button" disabled={!canPack} onClick={() => pack('stack')}>Pack into scrollable stack</button>
          <button type="button" disabled={!selected.length} onClick={remove}>{selectedContainer ? 'Unpack container' : 'Remove selected'}</button>
        </fieldset>
        {object && !members.has(selected[0]) && <fieldset disabled={!canEdit}><legend>Position and size</legend>
          <NumberField label="X" value={object.x} min={0} max={layout.width - object.width} change={x => change(boxesChanged({ [selected[0]]: { x } }))} />
          <NumberField label="Y" value={object.y} min={0} max={layout.height - object.height} change={y => change(boxesChanged({ [selected[0]]: { y } }))} />
          <NumberField label="Width" value={object.width} min={32} max={layout.width - object.x} change={width => change(boxesChanged({ [selected[0]]: { width } }))} />
          <NumberField label="Height" value={object.height} min={24} max={layout.height - object.y} change={height => change(boxesChanged({ [selected[0]]: { height } }))} />
          {selectedContainer?.mode === 'grid' && <NumberField label="Grid columns" value={selectedContainer.columns} min={1} max={8}
            change={columns => change(boxesChanged({ [selected[0]]: { columns } }))} />}
        </fieldset>}
        <fieldset disabled={!canEdit} className="canvas-properties">
          <Properties item={item} component={config.components[item?.type]} onChange={(key, value) =>
            change(layout, data.content.map(block => block === item ? { ...block, props: { ...block.props, [key]: value } } : block))} />
        </fieldset>
      </aside>
    </div>
  </section>;
}
