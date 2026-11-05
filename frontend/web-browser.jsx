import React, { useContext, useEffect, useRef, useState } from 'react';
import { Live, Quality, tagValue } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';
import './web-browser.css';

const dns = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const ipv4 = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/;
const plainPath = /^\/[a-zA-Z0-9._~/-]*$/;
const fullAddress = /^(https?):\/\/([a-z0-9.-]+)(?::([1-9][0-9]{0,4}))?(\/[a-zA-Z0-9._~/-]*)?$/i;
const defaultPort = { http: 80, https: 443 };
const refreshIntervalMs = 1000;

function destination({ scheme, hosts, port, path }, address, hmiHost) {
  const approved = hosts.split(',').map(host => host.trim().toLowerCase());
  if (!Object.hasOwn(defaultPort, scheme) || !plainPath.test(path) || path.includes('//')
      || path.split('/').some(segment => segment === '.' || segment === '..')
      || (port != null && (!Number.isInteger(port) || port < 1 || port > 65535))) return null;
  const value = address?.trim();
  const match = value?.match(fullAddress);
  const host = address === undefined ? approved[0] : (match?.[2] || value).toLowerCase();
  if (host === hmiHost || !approved.includes(host) || !(dns.test(host) || ipv4.test(host))) return null;
  if (match && (match[1].toLowerCase() !== scheme || Number(match[3] || defaultPort[scheme]) !== (port ?? defaultPort[scheme])
    || (match[4] || '/') !== path)) return null;
  try {
    const url = new URL(scheme + '://' + host + (port == null ? '' : ':' + port) + path);
    return url.hostname === host && url.pathname === path ? url : null;
  } catch {
    return null;
  }
}

function frameDocument(url) {
  // The validated URL contains only literal host, port and plain path characters.
  // The outer document constrains the nested frame's origin, including redirects.
  return '<!doctype html><meta charset="utf-8">'
    + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; '
    + 'form-action \'none\'; style-src \'unsafe-inline\'; frame-src ' + url.origin + '">'
    + '<meta name="referrer" content="no-referrer">'
    + '<style>html,body,iframe{margin:0;width:100%;height:100%;border:0;display:block}</style>'
    + '<iframe sandbox="allow-scripts" credentialless referrerpolicy="no-referrer" src="' + url.href + '"></iframe>';
}

function CameraPage({ url, label, refreshTag }) {
  const live = useContext(Live);
  const { ui } = useLocalization();
  const mixedContent = window.location.protocol === 'https:' && url.protocol === 'http:';
  const embed = !mixedContent && 'credentialless' in HTMLIFrameElement.prototype;
  const trigger = refreshTag ? tagValue(live, refreshTag) : null;
  const refreshValue = trigger?.valid && (typeof trigger.value === 'boolean' || Number.isSafeInteger(trigger.value))
    ? trigger.value : undefined;
  const baseline = useRef(null);
  const lastReload = useRef(performance.now());
  const timer = useRef(null);
  const [generation, setGeneration] = useState(0);
  const [loaded, setLoaded] = useState(null);

  function requestReload() {
    if (timer.current !== null) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      lastReload.current = performance.now();
      setGeneration(previous => previous + 1);
    }, Math.max(0, refreshIntervalMs - (performance.now() - lastReload.current)));
  }

  useEffect(() => {
    const previous = baseline.current;
    baseline.current = { tag: refreshTag, value: refreshValue };
    if (!embed || previous?.tag !== refreshTag || typeof previous.value !== typeof refreshValue) return;
    if (typeof refreshValue === 'boolean' ? !previous.value && refreshValue
      : refreshValue !== undefined && refreshValue !== previous.value) requestReload();
  }, [embed, refreshTag, refreshValue]);
  useEffect(() => () => clearTimeout(timer.current), []);

  return <>
    <div className="camera-actions">
      {embed && <button type="button" onClick={requestReload}>{ui('cameraRefresh')}</button>}
      <button type="button" onClick={() => window.open(url.href, '_blank', 'noopener,noreferrer')}>{ui('cameraOpenTab')}</button>
      {trigger && refreshValue === undefined && <Quality problem={trigger.problem || 'badData'} tag={refreshTag} />}
    </div>
    <small className="camera-status" role="status">{ui(!embed ? (mixedContent ? 'cameraMixedContent' : 'cameraIsolationUnavailable')
      : loaded === generation ? 'cameraUnverified' : 'cameraOpening')}</small>
    {embed && <iframe key={generation} className="camera-frame" title={label} sandbox="allow-scripts"
      referrerPolicy="no-referrer" srcDoc={frameDocument(url)} onLoad={() => setLoaded(generation)} />}
  </>;
}

export function WebBrowser({ id, label, scheme = 'https', hosts = '', port, path = '/', address_tag = '', refresh_tag = '', puck }) {
  const live = useContext(Live);
  const { text, ui } = useLocalization();
  const title = text('control.' + id + '.label', label);
  const address = address_tag ? tagValue(live, address_tag, 'string') : null;
  const url = !puck?.isEditing && (!address || address.valid)
    ? destination({ scheme, hosts, port, path }, address?.value, window.location.hostname) : null;
  return <article className="hmi-control hmi-camera" data-control="web_browser">
    <span className="hmi-label">{title}</span>
    {puck?.isEditing ? <p>{ui('cameraDesigner')}</p>
      : address && !address.valid ? <Quality problem={address.problem} tag={address_tag} />
        : url ? <CameraPage key={url.href} url={url} label={title} refreshTag={refresh_tag} />
          : <Quality problem="cameraAddressBlocked" />}
  </article>;
}
