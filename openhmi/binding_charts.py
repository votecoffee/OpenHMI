"""Live chart and historian trend binding rules."""

from fastapi import HTTPException
from .screens import CHART_TAG_FIELDS, chart_tags


def validate_chart_control(control, kinds):
    if control['kind'] in CHART_TAG_FIELDS:
        tags = chart_tags(control)
        if any(kinds.get(tag) not in ('number', 'integer') for tag in tags):
            raise HTTPException(422, 'Live charts require numeric tags')
        if control['kind'] == 'pie' and len(set(tags)) != len(tags):
            raise HTTPException(422, 'Pie slices require distinct tags')
        return True
    if control['kind'] == 'trend':
        if any(kinds.get(tag) not in ('number', 'integer', 'boolean') for tag in control['tags']):
            raise HTTPException(422, 'Trend requires numeric or Boolean tags')
        recording = control.get('recording')
        if recording and any(recording[field] and kinds.get(recording[field]) != 'boolean' for field in ('start_tag', 'stop_tag')):
            raise HTTPException(422, 'Trend recording triggers require Boolean tags')
        if recording and recording['start_tag'] and recording['start_tag'] == recording['stop_tag']:
            raise HTTPException(422, 'Trend recording triggers must resolve to different tags')
        return True
    return False
