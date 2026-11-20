import React, { useContext } from 'react';
import { Live } from './live-quality.jsx';
import { useLocalization } from './localization.jsx';

export function RecipePicture({ content }) {
  const { ui } = useLocalization();
  return content?.image_id ? <img className="recipe-image" src={`/api/recipe-images/${content.image_id}`} alt={content.title} />
    : <div className="recipe-no-image">{ui('recipeNoImage')}</div>;
}

export function LoadedRecipe({ compact = false }) {
  const live = useContext(Live);
  const { ui } = useLocalization();
  const selected = live.recipeSelection?.snapshot;
  if (!live.recipeConnected) return <p className="hmi-quality">{ui('recipeUnavailable')}</p>;
  if (!selected) return <p>{ui('recipeNotLoaded')}</p>;
  return <div className={`loaded-recipe ${compact ? 'compact' : ''}`}>
    <RecipePicture content={selected.content} />
    <div><strong>{selected.content.title}</strong><p>{selected.code} / {ui('recipeRevision')} {selected.number}</p>
      <p className="recipe-production">{selected.production_approved ? ui('recipeProduction') : ui('recipeTest')}</p>
      {!compact && <><p>{ui('recipeLoadedBy')}: {selected.loaded_by} · {selected.loaded_at}</p>
        {selected.approved_by && <p>{ui('recipeApprovedBy')}: {selected.approved_by}</p>}
        <ParameterValues content={selected.content} /></>}
    </div>
  </div>;
}

export function ParameterValues({ content }) {
  const { ui } = useLocalization();
  return <table className="recipe-values"><thead><tr><th>{ui('recipeParameter')}</th><th>{ui('recipeValue')}</th><th>{ui('recipeUnits')}</th></tr></thead>
    <tbody>{content.parameters.map(parameter => <tr key={parameter.name}><td>{parameter.label}</td>
      <td>{typeof parameter.value === 'boolean' ? ui(parameter.value ? 'on' : 'off') : String(parameter.value)}</td><td>{parameter.unit}</td></tr>)}</tbody></table>;
}

export function SelectedRecipe({ id, label }) {
  const { text } = useLocalization();
  return <article className="hmi-control hmi-recipe" data-control="recipe"><span className="hmi-label">{text(`control.${id}.label`, label)}</span>
    <LoadedRecipe compact /></article>;
}
