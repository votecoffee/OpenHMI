import React from 'react';

export function TagReference({ tag, puck }) {
  return puck?.isEditing ? <span className="hmi-source">{tag}</span> : null;
}

export function formatNumeric(value, decimals, locale, signed = false) {
  const options = { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: false };
  try {
    return new Intl.NumberFormat(locale, { ...options, signDisplay: signed ? 'exceptZero' : 'auto' }).format(value);
  } catch {
    const formatted = value.toFixed(decimals);
    return signed && Number(formatted) > 0 ? '+' + formatted : formatted;
  }
}
