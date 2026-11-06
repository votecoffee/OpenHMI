import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from './api.mjs';
import { useLocalization } from './localization.jsx';
import './canvas.css';

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const id = () => 'canvas-' + crypto.randomUUID();
const HISTORY_LIMIT = 60;
const ZOOM_LEVELS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
const NUDGE = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
const maxX = box => box.x + box.width;
const maxY = box => box.y + box.height;
const settings = (layout, key, value) => ({ ...layout, [key]: value });
const lookup = (map, key) => map && Object.hasOwn(map, key) ? map[key] : undefined;

function size(type) {
  if (type === 'StaticLabel') return { width: 144, height: 32 };
  if (type === 'RadialGauge') return { width: 176, height: 160 };
  if (type === 'DateTimeDisplay') return { width: 208, height: 56 };
  if (type === 'LedDisplay') return { width: 176, height: 64 };
  if (type === 'DurationDisplay') return { width: 144, height: 56 };
  if (type === 'StackLight') return { width: 160, height: 128 };
  if (type === 'Sparkline') return { width: 176, height: 104 };
  if (type === 'ScreenSymbol') return { width: 48, height: 48 };
  if (type === 'Trend') return { width: 480, height: 320 };
  if (type === 'WebBrowser') return { width: 400, height: 280 };
  if (['TankLevel', 'BarGraph', 'RadarChart', 'PieChart', 'XYChart', 'Faceplate'].includes(type)) return { width: 240, height: 240 };
  return { width: 176, height: 80 };
}

export function initialCanvas(data) {
  const columns = data.root.props.columns || 2;
  const width = Math.max(1024, columns * 340);
  const boxes = Object.create(null);
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
  return { width, height, grid: 8, snap: true, background: '', boxes, containers: {}, decorations: {} };
}

function bounds(boxes) {
  const x = Math.min(...boxes.map(box => box.x)), y = Math.min(...boxes.map(box => box.y));
  return { x, y, width: Math.max(...boxes.map(maxX)) - x, height: Math.max(...boxes.map(maxY)) - y };
}

const memberIDs = layout => new Set(Object.values(layout.containers).flatMap(container => container.members));
const decorationEntries = layout => Object.entries(layout.decorations ?? {});
const objectEntries = layout => [...Object.entries(layout.boxes), ...Object.entries(layout.containers), ...decorationEntries(layout)];
const topObjects = layout => {
  const members = memberIDs(layout);
  return objectEntries(layout).filter(([key, object]) => !members.has(key) && !object.locked).sort((a, b) => a[1].z - b[1].z);
};
const boxStyle = box => ({ left: box.x, top: box.y, width: box.width, height: box.height, zIndex: box.z + 1 });

function Decoration({ object }) {
  return object.kind === 'image'
    ? <img className="canvas-decoration-art" src={'/api/canvas-images/' + object.image} alt="" draggable={false} />
    : <span className={`canvas-decoration-art canvas-decoration-${object.kind}`} style={{ backgroundColor: object.fill }} aria-hidden="true" />;
}

function renderBlock(config, item, editing) {
  const component = config.components[item.type];
  return component?.render({ ...component.defaultProps, ...item.props, puck: { isEditing: editing } });
}

export function CanvasSurface({ data, config, editor }) {
  const { layout } = data.root.props;
  const content = new Map(data.content.map(item => [item.props.id, item]));
  const editing = !!editor;
  const { ui } = useLocalization();
  const runtimeViewport = useRef(null);
  const [fit, setFit] = useState(false);
  const [fitZoom, setFitZoom] = useState(1);
  useLayoutEffect(() => {
    if (editing || !fit) return;
    const viewport = runtimeViewport.current;
    function resize() {
      if (viewport.clientWidth > 0) setFitZoom(Math.min(1, viewport.clientWidth / layout.width));
    }
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [editing, fit, layout.width]);
  const zoom = editing ? editor.zoom : fit ? fitZoom : 1;
  return <>{!editing && <div className="canvas-view-controls" role="group" aria-label={ui('canvasDisplay')}>
    <button type="button" aria-pressed={!fit} onClick={() => setFit(false)}>{ui('canvasActualSize')}</button>
    <button type="button" aria-pressed={fit} onClick={() => setFit(true)}>{ui('canvasFitWidth')}</button>
    <span>{ui('canvasDisplayScale', { percent: Math.round(zoom * 100) })}</span>
  </div>}
  <div ref={editor?.viewport ?? runtimeViewport}
    className={`canvas-scroll${editor?.panMode ? ' canvas-pan-mode' : ''}${editor?.panning ? ' canvas-panning' : ''}`} dir="ltr"
    onPointerDownCapture={editor?.startPan}
    onPointerMove={editor?.movePan}
    onPointerUp={editor?.finishPan}
    onPointerCancel={editor?.finishPan}
    onLostPointerCapture={editor?.finishPan}
    onClickCapture={editor?.panMode ? event => { event.preventDefault(); event.stopPropagation(); } : undefined}>
    <div ref={editor?.surface} className={`hmi-canvas${editing && layout.snap ? ' canvas-grid' : ''}`} dir="ltr"
      aria-label={editing ? 'Freeform canvas' : 'Freeform screen'}
      style={{ width: layout.width, height: layout.height, '--canvas-grid': layout.grid + 'px', zoom }}
      onClick={event => {
        if (event.target === event.currentTarget && event.nativeEvent.pointerType === 'touch') editor?.clearSelection();
      }}
      onPointerDown={editor?.startMarquee}
      onPointerMove={editor?.moveMarquee}
      onPointerUp={editor?.finishMarquee}
      onPointerCancel={editor?.cancelMarquee}
      onLostPointerCapture={editor?.cancelMarquee}
      onDragOver={editing ? event => event.preventDefault() : undefined}
      onDrop={editor?.drop}>
      {layout.background && <img className="canvas-background" src={'/api/canvas-images/' + layout.background} alt="" draggable={false} />}
      <div className="canvas-background-objects" aria-hidden="true">
        {decorationEntries(layout).filter(([, object]) => object.locked).sort((a, b) => a[1].z - b[1].z)
          .map(([key, object]) => <div key={key} data-canvas-object={key} data-background-locked=""
            className="canvas-object" style={boxStyle(object)}><Decoration object={object} /></div>)}
      </div>
      {topObjects(layout).map(([key, box]) => {
        const container = lookup(layout.containers, key), item = content.get(key), decoration = lookup(layout.decorations, key);
        const selection = editor?.selected.includes(key);
        const label = decoration?.label || item?.props.label || (container?.mode === 'grid' ? 'Grid container' : 'Scrollable stack');
        return <div key={key} data-canvas-object={key} className={`canvas-object${selection ? ' canvas-selected' : ''}${decoration && !editing ? ' canvas-decorative' : ''}`} style={boxStyle(box)}>
          <div className="canvas-object-body" inert={editing || undefined}>
            {decoration ? <Decoration object={decoration} /> : container ? <div className={`canvas-container canvas-container-${container.mode}`}
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
      {editor?.marquee && <div className="canvas-marquee" aria-hidden="true"
        style={{ left: editor.marquee.x, top: editor.marquee.y, width: editor.marquee.width, height: editor.marquee.height }} />}
    </div>
  </div></>;
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

export function CanvasEditor({ data, config, onChange, canEdit, clipboard, onCopy }) {
  const { layout } = data.root.props;
  const [selected, select] = useState([]);
  const [objectQuery, setObjectQuery] = useState('');
  const [sizeReference, setSizeReference] = useState('');
  const [palette, setPalette] = useState(Object.keys(config.components)[0]);
  const [view, setView] = useState({ zoom: 1, center: null });
  const { zoom } = view;
  const [preview, setPreview] = useState(null);
  const [marquee, setMarquee] = useState(null);
  const [panMode, setPanMode] = useState(false);
  const [panning, setPanning] = useState(false);
  const [message, setMessage] = useState('');
  const surface = useRef(null);
  const viewport = useRef(null);
  const editorRegion = useRef(null);
  const pendingImage = useRef(0);
  const latest = useRef({ data, onChange, canEdit, selected });
  latest.current = { data, onChange, canEdit, selected };
  const history = useRef({ undo: [], redo: [], field: '' }).current;
  const dragging = useRef(false);
  const marqueeDrag = useRef(null);
  const panDrag = useRef(null);
  useEffect(() => () => { pendingImage.current += 1; }, []);
  useLayoutEffect(() => {
    if (!view.center || !viewport.current) return;
    const element = viewport.current;
    element.scrollLeft = view.center.x * view.zoom - element.clientWidth / 2;
    element.scrollTop = view.center.y * view.zoom - element.clientHeight / 2;
  }, [view]);

  const members = memberIDs(layout);
  const item = selected.length === 1 ? data.content.find(entry => entry.props.id === selected[0]) : null;
  const selectedContainer = selected.length === 1 ? lookup(layout.containers, selected[0]) : null;
  const decoration = selected.length === 1 ? lookup(layout.decorations, selected[0]) : null;
  const object = selected.length === 1 ? lookup(layout.boxes, selected[0]) || selectedContainer || decoration : null;
  const freeSelection = selected.filter(key => !members.has(key) && (lookup(layout.boxes, key) || lookup(layout.containers, key) || lookup(layout.decorations, key)));
  const top = topObjects(layout);
  const objects = Object.fromEntries(objectEntries(layout));
  const referenceID = freeSelection.includes(sizeReference) ? sizeReference : freeSelection[0];
  const reference = objects[referenceID];

  function objectLabel(key) {
    return lookup(layout.decorations, key)?.label || data.content.find(block => block.props.id === key)?.props.label
      || (objects[key]?.mode === 'grid' ? 'Grid container' : 'Scrollable stack');
  }

  const query = objectQuery.trim().toLowerCase();
  const matchesObject = key => key.toLowerCase().includes(query) || objectLabel(key).toLowerCase().includes(query);
  const outline = top.flatMap(([key, box]) => {
    const matches = matchesObject(key);
    const children = (box.members ?? []).filter(member => matches || matchesObject(member));
    return matches || children.length ? [{ key, children }] : [];
  });
  const lockedOutline = decorationEntries(layout).filter(([key, box]) => box.locked && matchesObject(key));

  function matchSizeOptions() {
    if (freeSelection.length < 2) return [];
    return [
      ['Match width', { width: reference.width }],
      ['Match height', { height: reference.height }],
      ['Match size', { width: reference.width, height: reference.height }],
    ].map(([label, dimensions]) => {
      const changed = freeSelection.filter(key => Object.entries(dimensions).some(([field, value]) => objects[key][field] !== value));
      const fits = changed.every(key => {
        const box = { ...objects[key], ...dimensions };
        return maxX(box) <= layout.width && maxY(box) <= layout.height;
      });
      return { label, dimensions, changed, fits };
    });
  }

  function publish(next) {
    latest.current.data = next;
    latest.current.onChange(next);
  }

  function commit(next, field = '') {
    const current = latest.current;
    if (!current.canEdit) return;
    if (!field || history.field !== field) {
      history.undo.push({ data: current.data, selected: current.selected });
      if (history.undo.length > HISTORY_LIMIT) history.undo.shift();
    }
    history.field = field;
    history.redo.length = 0;
    publish(next);
  }

  function change(next, content = latest.current.data.content, field = '') {
    commit({ root: { props: { ...latest.current.data.root.props, layout: next } }, content }, field);
  }

  function restore(direction) {
    const current = latest.current;
    if (!current.canEdit || dragging.current || !history[direction].length) return;
    const target = history[direction].pop();
    history[direction === 'undo' ? 'redo' : 'undo'].push({ data: current.data, selected: current.selected });
    history.field = '';
    pendingImage.current += 1;
    setMessage('');
    select(target.selected);
    publish(target.data);
    editorRegion.current?.focus({ preventScroll: true });
  }

  function canvasShortcut(event) {
    if (event.key === 'Escape' && (panMode || panDrag.current)) {
      event.preventDefault();
      finishPan();
      setPanMode(false);
      return;
    }
    if (event.key === 'Escape' && marqueeDrag.current) {
      event.preventDefault();
      cancelMarquee();
      return;
    }
    if (!canEdit || dragging.current || marqueeDrag.current || panDrag.current || event.altKey ||
        event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    const command = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    if (command && (key === 'z' || key === 'y')) {
      event.preventDefault();
      restore(key === 'y' || event.shiftKey ? 'redo' : 'undo');
    } else if (command && key === 'c' && canCopy) {
      event.preventDefault();
      if (!event.repeat) copySelection();
    } else if (command && key === 'v' && canPaste) {
      event.preventDefault();
      if (!event.repeat) paste(clipboard);
    } else if (command && key === 'd' && canDuplicate) {
      event.preventDefault();
      if (!event.repeat) paste(selection);
    } else if (!command && freeSelection.length && Object.hasOwn(NUDGE, event.key)) {
      event.preventDefault();
      const [x, y] = NUDGE[event.key];
      const step = event.shiftKey ? layout.grid : 1;
      const field = 'nudge:' + event.key + ':' + step + ':' + freeSelection.join(',');
      if (!event.repeat) history.field = '';
      nudge(x * step, y * step, field);
    }
  }

  function boxesChanged(changes, original = layout) {
    const next = { ...original, boxes: { ...original.boxes }, containers: { ...original.containers }, decorations: { ...original.decorations } };
    for (const [key, patch] of Object.entries(changes)) {
      const map = Object.hasOwn(next.boxes, key) ? next.boxes : Object.hasOwn(next.containers, key) ? next.containers : next.decorations;
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
    element.focus({ preventScroll: true });
    const startX = event.clientX, startY = event.clientY;
    const snap = value => layout.snap ? Math.round(value / layout.grid) * layout.grid : Math.round(value);
    let changes, moved = false;
    element.setPointerCapture(event.pointerId);
    dragging.current = true;
    function move(pointer) {
      const dx = (pointer.clientX - startX) / zoom, dy = (pointer.clientY - startY) / zoom;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      moved = true;
      if (resize) {
        changes = { [key]: {
          width: clamp(snap(anchor.width + dx), 32, layout.width - anchor.x),
          height: clamp(snap(anchor.height + dy), 24, layout.height - anchor.y),
        } };
      } else {
        const x = clamp(snap(anchor.x + dx) - anchor.x, -area.x, layout.width - maxX(area));
        const y = clamp(snap(anchor.y + dy) - anchor.y, -area.y, layout.height - maxY(area));
        changes = Object.fromEntries(keys.map(name => [name, { x: objects[name].x + x, y: objects[name].y + y }]));
      }
      setPreview(boxesChanged(changes));
    }
    function finish(pointer) {
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerup', finish);
      element.removeEventListener('pointercancel', finish);
      element.removeEventListener('lostpointercapture', finish);
      dragging.current = false;
      setPreview(null);
      if (pointer.type === 'pointerup' && changes && Object.entries(changes).some(([name, patch]) =>
        Object.entries(patch).some(([key, value]) => objects[name][key] !== value))) {
        change(boxesChanged(changes, latest.current.data.root.props.layout));
      }
    }
    element.addEventListener('pointermove', move);
    element.addEventListener('pointerup', finish);
    element.addEventListener('pointercancel', finish);
    element.addEventListener('lostpointercapture', finish);
  }

  const roots = top.filter(([key]) => freeSelection.includes(key));
  const controlIDs = new Set(roots.flatMap(([key, object]) =>
    object.members ?? (lookup(layout.boxes, key) ? [key] : [])));
  const selection = {
    roots,
    boxes: Object.fromEntries([...controlIDs].map(key => [key, layout.boxes[key]])),
    content: data.content.filter(block => controlIDs.has(block.props.id)),
  };
  const canCopy = roots.length > 0 && roots.length === selected.length;
  const canDuplicate = canCopy && fits(selection);
  const canPaste = clipboard && fits(clipboard);

  function fits(source) {
    const area = bounds(source.roots.map(([, object]) => object));
    return area.width <= layout.width && area.height <= layout.height
      && Object.values(source.boxes).every(box => box.width <= layout.width && box.height <= layout.height)
      && data.content.length + source.content.length <= 100
      && Object.keys(layout.containers).length + source.roots.filter(([, object]) => object.members).length <= 30
      && decorationEntries(layout).length + source.roots.filter(([, object]) => object.kind).length <= 60;
  }

  function copySelection() {
    if (!canCopy) return;
    onCopy(structuredClone(selection));
    setMessage('Copied selection. Paste on this screen or another freeform screen in this project.');
  }

  function paste(source) {
    if (!source || !fits(source)) return;
    const copies = new Map([...new Set([...source.roots.map(([key]) => key), ...Object.keys(source.boxes)])]
      .map(key => [key, id()]));
    const groups = new Map();
    const area = bounds(source.roots.map(([, object]) => object));
    const step = layout.snap ? layout.grid : 8;
    const offset = (before, after) => {
      const preferred = after >= step ? step : before >= step ? -step : after || -before;
      return clamp(preferred, -before, after);
    };
    const dx = offset(area.x, layout.width - maxX(area));
    const dy = offset(area.y, layout.height - maxY(area));
    const next = boxesChanged(Object.fromEntries(top.map(([key], z) => [key, { z }])));
    for (const [key, box] of Object.entries(source.boxes)) next.boxes[copies.get(key)] = { ...box, group: '' };
    source.roots.forEach(([key, original], index) => {
      if (original.group && !groups.has(original.group)) groups.set(original.group, id());
      const copy = { ...original, x: original.x + dx, y: original.y + dy,
        z: top.length + index, group: groups.get(original.group) ?? '' };
      const newKey = copies.get(key);
      if (original.members) {
        next.containers[newKey] = { ...copy, members: original.members.map(member => copies.get(member)) };
        for (const member of original.members) {
          const box = next.boxes[copies.get(member)];
          box.x = clamp(box.x + dx, 0, layout.width - box.width);
          box.y = clamp(box.y + dy, 0, layout.height - box.height);
        }
      } else if (original.kind) next.decorations[newKey] = copy;
      else next.boxes[newKey] = copy;
    });
    const content = source.content.map(block => ({ ...block, props: { ...structuredClone(block.props), id: copies.get(block.props.id) } }));
    change(next, [...data.content, ...content]);
    select(source.roots.map(([key]) => copies.get(key)));
    editorRegion.current?.focus({ preventScroll: true });
    setMessage('');
  }

  function nudge(dx, dy, field) {
    const area = bounds(freeSelection.map(key => objects[key]));
    const x = clamp(dx, -area.x, layout.width - maxX(area));
    const y = clamp(dy, -area.y, layout.height - maxY(area));
    if (!x && !y) return;
    change(boxesChanged(Object.fromEntries(freeSelection.map(key => [key, {
      x: objects[key].x + x, y: objects[key].y + y,
    }]))), data.content, field);
  }

  const layerIDs = top.map(([key]) => key);
  const chosenLayers = new Set(freeSelection);
  const canStep = direction => layerIDs.some((key, index) => {
    const neighbor = index + direction;
    return chosenLayers.has(key) && neighbor >= 0 && neighbor < layerIDs.length && !chosenLayers.has(layerIDs[neighbor]);
  });

  function saveLayers(order) {
    change(boxesChanged(Object.fromEntries(order.map((key, z) => [key, { z }]))));
  }

  function reorder(front) {
    const chosen = layerIDs.filter(key => chosenLayers.has(key));
    const other = layerIDs.filter(key => !chosenLayers.has(key));
    saveLayers(front ? [...other, ...chosen] : [...chosen, ...other]);
  }

  function stepLayer(direction) {
    const order = [...layerIDs];
    const start = direction === 1 ? order.length - 2 : 1;
    for (let index = start; index >= 0 && index < order.length; index -= direction) {
      const neighbor = index + direction;
      if (chosenLayers.has(order[index]) && !chosenLayers.has(order[neighbor])) {
        [order[index], order[neighbor]] = [order[neighbor], order[index]];
      }
    }
    saveLayers(order);
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
    const next = { ...layout, boxes: { ...layout.boxes }, containers: { ...layout.containers }, decorations: { ...layout.decorations } };
    for (const key of selected) { delete next.boxes[key]; delete next.containers[key]; delete next.decorations[key]; }
    for (const [key, container] of Object.entries(next.containers)) {
      next.containers[key] = { ...container, members: container.members.filter(member => !selected.includes(member)) };
    }
    change(next, data.content.filter(block => !selected.includes(block.props.id)));
    select([]);
  }

  function addDecoration(kind, label, image = '') {
    const current = latest.current.data;
    const activeLayout = current.root.props.layout;
    if (!latest.current.canEdit || decorationEntries(activeLayout).length >= 60) return;
    const key = id();
    const box = { kind, label, image, fill: '#aaaaaa', locked: false, x: 8, y: 8,
      width: Math.min(240, activeLayout.width - 8), height: Math.min(160, activeLayout.height - 8),
      z: topObjects(activeLayout).length, group: '' };
    const next = { ...activeLayout, decorations: { ...activeLayout.decorations, [key]: box } };
    commit({ ...current, root: { props: { ...current.root.props, layout: next } } });
    select([key]);
  }

  function lockBackground() {
    change(boxesChanged(Object.fromEntries(freeSelection.map(key => [key, { locked: true, group: '' }]))));
    select([]);
  }

  async function background(file, asObject = false) {
    if (!file || !canEdit) return;
    const request = ++pendingImage.current;
    try {
      setMessage('Uploading image...');
      const image = await api('/api/canvas-images', { method: 'POST', body: file, signal: AbortSignal.timeout(15000) });
      if (request !== pendingImage.current) return;
      if (asObject) addDecoration('image', file.name.slice(0, 100) || 'Image', image.id);
      else if (latest.current.data.root.props.layout.background !== image.id) {
        change(settings(latest.current.data.root.props.layout, 'background', image.id));
      }
      setMessage('');
    } catch (error) { if (request === pendingImage.current) setMessage(error.message); }
  }

  function changeZoom(next) {
    const element = viewport.current;
    if (!element) return;
    setView({ zoom: next, center: {
      x: (element.scrollLeft + element.clientWidth / 2) / zoom,
      y: (element.scrollTop + element.clientHeight / 2) / zoom,
    } });
  }

  function fitView(area) {
    const element = viewport.current;
    if (!element || element.clientWidth <= 24) return;
    const height = Number.parseFloat(getComputedStyle(element).maxHeight) || element.clientHeight;
    const factor = Math.min((element.clientWidth - 24) / area.width, (height - 24) / area.height);
    setView({ zoom: clamp(Math.floor(factor * 100) / 100, 0.01, 2), center: {
      x: area.x + area.width / 2, y: area.y + area.height / 2,
    } });
  }

  function startPan(event) {
    if (event.button !== 1 && (!panMode || event.button !== 0)) return;
    if (!event.isPrimary || dragging.current || marqueeDrag.current || panDrag.current) return;
    event.preventDefault();
    event.stopPropagation();
    const element = event.currentTarget;
    editorRegion.current?.focus({ preventScroll: true });
    element.setPointerCapture(event.pointerId);
    panDrag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      left: element.scrollLeft, top: element.scrollTop };
    setPanning(true);
  }

  function movePan(event) {
    const drag = panDrag.current;
    if (drag?.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = drag.left + drag.x - event.clientX;
    event.currentTarget.scrollTop = drag.top + drag.y - event.clientY;
  }

  function finishPan(event) {
    const drag = panDrag.current;
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    panDrag.current = null;
    setPanning(false);
    if (viewport.current?.hasPointerCapture(drag.pointerId)) viewport.current.releasePointerCapture(drag.pointerId);
  }

  function canvasPoint(event) {
    const rect = surface.current.getBoundingClientRect();
    return {
      x: clamp((event.clientX - rect.left) / zoom, 0, layout.width),
      y: clamp((event.clientY - rect.top) / zoom, 0, layout.height),
    };
  }

  function startMarquee(event) {
    if (event.target !== event.currentTarget || event.button !== 0 || event.pointerType === 'touch'
        || dragging.current || marqueeDrag.current) return;
    event.preventDefault();
    editorRegion.current?.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    marqueeDrag.current = { pointerId: event.pointerId, start: canvasPoint(event), extend: event.shiftKey };
  }

  function selectionBox(event, drag) {
    const end = canvasPoint(event), start = drag.start;
    const width = Math.abs(end.x - start.x), height = Math.abs(end.y - start.y);
    if (Math.max(width, height) * zoom < 3) return null;
    return { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width, height };
  }

  function moveMarquee(event) {
    const drag = marqueeDrag.current;
    if (drag?.pointerId === event.pointerId) setMarquee(selectionBox(event, drag));
  }

  function cancelMarquee(event) {
    const drag = marqueeDrag.current;
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    marqueeDrag.current = null;
    setMarquee(null);
    if (surface.current?.hasPointerCapture(drag.pointerId)) surface.current.releasePointerCapture(drag.pointerId);
  }

  function finishMarquee(event) {
    const drag = marqueeDrag.current;
    if (drag?.pointerId !== event.pointerId) return;
    const area = selectionBox(event, drag);
    cancelMarquee(event);
    if (!area) {
      if (!drag.extend) select([]);
      return;
    }
    const hits = top.filter(([, box]) => box.x < maxX(area) && maxX(box) > area.x
      && box.y < maxY(area) && maxY(box) > area.y);
    const groups = new Set(hits.map(([, box]) => box.group).filter(Boolean));
    const keys = new Set(hits.map(([key]) => key));
    const matched = top.filter(([key, box]) => keys.has(key) || groups.has(box.group)).map(([key]) => key);
    select(drag.extend ? [...new Set([...selected, ...matched])] : matched);
  }

  function drop(event) {
    event.preventDefault();
    add(event.dataTransfer.getData('application/x-openhmi-control'), canvasPoint(event));
  }

  const canvasData = preview ? { ...data, root: { props: { ...data.root.props, layout: preview } } } : data;
  const canLock = freeSelection.length > 0 && freeSelection.every(key => lookup(layout.decorations, key));
  const canAddDecoration = decorationEntries(layout).length < 60;
  const canPack = freeSelection.length > 0 && freeSelection.every(key => lookup(layout.boxes, key)) && Object.keys(layout.containers).length < 30;
  const minWidth = Math.max(160, ...Object.values(objects).map(maxX));
  const minHeight = Math.max(120, ...Object.values(objects).map(maxY));
  return <section ref={editorRegion} tabIndex={-1} className="canvas-editor" aria-label="Freeform designer" onKeyDown={canvasShortcut}
    onBlurCapture={() => { history.field = ''; }}>
    <fieldset className="canvas-toolbar" disabled={!canEdit}><legend>Canvas tools</legend>
      <button type="button" disabled={!history.undo.length} onClick={() => restore('undo')}>Undo</button>
      <button type="button" disabled={!history.redo.length} onClick={() => restore('redo')}>Redo</button>
      <label>Screen name<input value={data.root.props.title} maxLength={120}
        onChange={event => commit({ ...data, root: { props: { ...data.root.props, title: event.target.value } } }, 'screen-title')} /></label>
      <NumberField label="Canvas width" value={layout.width} min={minWidth} max={4096} change={value => change(settings(layout, 'width', value))} />
      <NumberField label="Canvas height" value={layout.height} min={minHeight} max={4096} change={value => change(settings(layout, 'height', value))} />
      <label><input type="checkbox" checked={layout.snap} onChange={event => change(settings(layout, 'snap', event.target.checked))} />Snap to grid</label>
      <NumberField label="Grid spacing" value={layout.grid} min={2} max={100} change={value => change(settings(layout, 'grid', value))} />
      <label>Zoom<select value={zoom} onChange={event => changeZoom(Number(event.target.value))}>
        {[...new Set([...ZOOM_LEVELS, zoom])].sort((a, b) => a - b)
          .map(value => <option key={value} value={value}>{Math.round(value * 100)}%</option>)}
      </select></label>
      <button type="button" onClick={() => fitView({ x: 0, y: 0, width: layout.width, height: layout.height })}>Fit canvas</button>
      <button type="button" disabled={!freeSelection.length}
        onClick={() => fitView(bounds(freeSelection.map(key => objects[key])))}>Fit selection</button>
      <button type="button" aria-pressed={panMode} onClick={() => setPanMode(value => !value)}>Pan canvas</button>
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
        <fieldset disabled={!canEdit || !canAddDecoration}><legend>Images and shapes</legend>
          <label>Image object<input type="file" accept="image/png,image/jpeg,image/webp"
            onChange={event => { background(event.target.files[0], true); event.target.value = ''; }} /></label>
          <button type="button" onClick={() => addDecoration('rectangle', 'Rectangle')}>Add rectangle</button>
          <button type="button" onClick={() => addDecoration('ellipse', 'Ellipse')}>Add ellipse</button>
        </fieldset>
        <fieldset><legend>Objects</legend>
          <label>Search objects<input type="search" value={objectQuery} placeholder="Name or ID"
            onChange={event => setObjectQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Escape' && objectQuery) {
                event.preventDefault();
                event.stopPropagation();
                setObjectQuery('');
              }
            }} /></label>
          {query && !outline.length && !lockedOutline.length && <small role="status">No matching objects.</small>}
          {outline.map(({ key, children }) => <React.Fragment key={key}>
            <button type="button" aria-pressed={selected.includes(key)} onClick={event => select(selectionFor(key, event.shiftKey))}>
              {objectLabel(key)}
            </button>
            {children.map(member => <button type="button" className="canvas-outline-member" key={member}
              aria-pressed={selected.includes(member)} onClick={() => select([member])}>{objectLabel(member)}</button>)}
          </React.Fragment>)}
          {lockedOutline.map(([key, entry]) => <div key={key} className="canvas-locked-outline">
            <span>{entry.label} (background)</span>
            <button type="button" disabled={!canEdit} aria-label={'Unlock ' + entry.label} onClick={() => {
              change(boxesChanged({ [key]: { locked: false } }));
              select([key]);
            }}>Unlock</button>
          </div>)}
        </fieldset>
      </aside>
      <CanvasSurface data={canvasData} config={config}
        editor={{ selected, selectObject: (key, extend) => select(selectionFor(key, extend)), begin, drop, surface, viewport, zoom,
          marquee, startMarquee, moveMarquee, finishMarquee, cancelMarquee, clearSelection: () => select([]),
          panMode, panning, startPan, movePan, finishPan }} />
      <aside className="canvas-tools">
        <fieldset disabled={!canEdit}><legend>Selection</legend>
          <small>Drag a box from empty canvas or Shift-click to select multiple objects. Use arrows to nudge.</small>
          <button type="button" disabled={!canDuplicate} onClick={() => paste(selection)}>Duplicate selection</button>
          <button type="button" disabled={!canCopy} onClick={copySelection}>Copy selection</button>
          <button type="button" disabled={!canPaste} onClick={() => paste(clipboard)}>Paste selection</button>
          {clipboard && !canPaste && <small>The copied objects exceed this canvas size or its object limits.</small>}
          <button type="button" disabled={!canLock} onClick={lockBackground}>Lock as background</button>
          <button type="button" disabled={!freeSelection.length} onClick={() => reorder(true)}>Bring to front</button>
          <button type="button" disabled={!freeSelection.length} onClick={() => reorder(false)}>Send to back</button>
          <button type="button" disabled={!canStep(1)} onClick={() => stepLayer(1)}>Bring forward</button>
          <button type="button" disabled={!canStep(-1)} onClick={() => stepLayer(-1)}>Send backward</button>
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
          {freeSelection.length > 1 && <>
            <label>Size reference<select value={referenceID} onChange={event => setSizeReference(event.target.value)}>
              {freeSelection.map(key => <option key={key} value={key}>
                {objectLabel(key)} ({objects[key].width} × {objects[key].height})
              </option>)}
            </select></label>
            {matchSizeOptions().map(({ label, dimensions, changed, fits }) => <button key={label} type="button"
              title={!fits ? 'The new size would extend outside the canvas' : undefined}
              disabled={!changed.length || !fits}
              onClick={() => change(boxesChanged(Object.fromEntries(changed.map(key => [key, dimensions]))))}>{label}</button>)}
          </>}

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
        {decoration && <fieldset disabled={!canEdit}><legend>Image or shape properties</legend>
          <label>Object label<input value={decoration.label} maxLength={100}
            onChange={event => change(boxesChanged({ [selected[0]]: { label: event.target.value } }), data.content, selected[0] + ':label')} /></label>
          {decoration.kind !== 'image' && <label>Fill color<input type="color" value={decoration.fill}
            onChange={event => change(boxesChanged({ [selected[0]]: { fill: event.target.value } }))} /></label>}
        </fieldset>}
        <fieldset disabled={!canEdit} className="canvas-properties">
          <Properties item={item} component={config.components[item?.type]} onChange={(key, value) =>
            change(layout, data.content.map(block => block === item ? { ...block, props: { ...block.props, [key]: value } } : block),
              config.components[item.type].fields[key].type === 'text' ? item.props.id + ':' + key : '')} />
        </fieldset>
      </aside>
    </div>
  </section>;
}
