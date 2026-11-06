"""Resolve edit limits from the same good-quality cached values as the input tag."""
import math

LIMIT_TAGS = ('minimum_tag', 'maximum_tag', 'min_length_tag', 'max_length_tag')
TEXT_INPUTS = ('text_input', 'text_area', 'barcode_input')


def edit_limits(control, values):
    text = control['kind'] in TEXT_INPUTS
    fields = ('min_length', 'max_length') if text else ('minimum', 'maximum')
    result = []
    for field in fields:
        tag = control.get(field + '_tag')
        value = values.get(tag) if tag else control[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Edit limit tag has no good-quality numeric value')
        if text and (value != int(value) or not 0 <= value <= 4096):
            raise ValueError('Text length limits must be integers between 0 and 4096')
        result.append(int(value) if text else value)
    if control['kind'] == 'slider' and not 0 < result[1] - result[0] < math.inf:
        raise ValueError('Slider range must have a positive, finite span')
    if result[0] > result[1]:
        raise ValueError('Edit minimum exceeds maximum')
    return result


def validate_entry(control, value, limits):
    if control['kind'] in TEXT_INPUTS:
        if type(value) is not str or not limits[0] <= len(value) <= limits[1] or '\x00' in value:
            raise ValueError('Text length is outside the configured limits or contains a null character')
        if control['kind'] == 'barcode_input' and (not value or '\r' in value or '\n' in value):
            raise ValueError('Barcode input requires one nonempty line')
    elif type(value) not in (int, float) or not math.isfinite(value) or not limits[0] <= value <= limits[1]:
        raise ValueError('Value is outside the configured input limits')
