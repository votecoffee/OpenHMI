import React from 'react';
import { ImageField, ImageStatesFields, MultiStateImage, MotionImage, StateImage, StaticImage } from './state-image.jsx';

export function createImagesPalette(catalog, fields) {
  const {
    tagField, browserTag, labelField, showImageLabel,
    integerTag, numericDefaults, motionImageFields,
  } = fields;
  return {
    StaticImage: { label: 'Image', fields: {
      label: labelField, alt_text: { type: 'text', label: 'Alternative text' },
      image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="Project image" /> },
      fit: { type: 'select', label: 'Image fit', options: [
        { label: 'Contain', value: 'contain' }, { label: 'Cover', value: 'cover' }, { label: 'Stretch', value: 'fill' },
      ] },
      show_label: { ...showImageLabel, label: 'Show caption' },
    }, defaultProps: { label: 'Image', image: '', alt_text: '', fit: 'contain', show_label: true },
    render: props => <StaticImage {...props} /> },
    StateImage: { label: 'State image', fields: {
      label: labelField, tag: tagField('boolean'),
      on_text: { type: 'text', label: 'ON text' }, off_text: { type: 'text', label: 'OFF text' },
      on_image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="ON image" /> },
      off_image: { type: 'custom', render: props => <ImageField key={props.id} {...props} label="OFF image" /> },
      show_label: showImageLabel,
    }, defaultProps: { label: 'Machine image', tag: 'MotorRunning', on_image: '', off_image: '',
      on_text: 'ON', off_text: 'OFF', show_label: true }, render: props => <StateImage {...props} /> },
    PositionImage: { label: 'Position image', fields: {
      ...motionImageFields,
      direction: { type: 'select', label: 'Travel direction', options: [
        { label: 'Left to right', value: 'left_to_right' }, { label: 'Right to left', value: 'right_to_left' },
        { label: 'Bottom to top', value: 'bottom_to_top' }, { label: 'Top to bottom', value: 'top_to_bottom' },
      ] },
      size_percent: { type: 'number', label: 'Marker size (%)', min: 10, max: 60 },
    }, defaultProps: { ...numericDefaults, label: 'Axis position', minimum: 0, maximum: 100, direction: 'left_to_right',
      size_percent: 25, image: '', show_label: true }, render: MotionImage },
    RotationImage: { label: 'Rotation image', fields: {
      ...motionImageFields,
      angle_start: { type: 'number', label: 'Start angle (degrees)', min: -360, max: 360 },
      angle_end: { type: 'number', label: 'End angle (degrees)', min: -360, max: 360 },
      size_percent: { type: 'number', label: 'Marker size (%)', min: 10, max: 70 },
    }, defaultProps: { ...numericDefaults, label: 'Rotation', minimum: 0, maximum: 100, angle_start: 0, angle_end: 360,
      size_percent: 50, image: '', show_label: true }, render: props => <MotionImage {...props} rotation /> },
    MultiStateImage: { label: 'Multi-state image', fields: {
      label: labelField, tag: browserTag('Tag', 'Choose an unscaled integer tag', integerTag),
      states: { type: 'custom', render: props => <ImageStatesFields key={props.id} {...props} /> },
      show_label: showImageLabel,
    }, defaultProps: { label: 'Machine position', tag: 'AlarmWord', show_label: true, states: [
      { value: 0, label: 'Stopped', image: '' }, { value: 1, label: 'Running', image: '' },
    ] }, render: props => <MultiStateImage {...props} /> },
  };
}
