import {FillLayer} from 'react-map-gl/maplibre';

const pointLayerStyle = {
    id: 'point',
    type: 'circle',
    paint: {
      'circle-radius': 10,
      'circle-color': '#007cbf'
    }
  };
// For more information on data-driven styles, see https://www.mapbox.com/help/gl-dds-ref/
export const dataLayer = {
    id: 'data',
    type: 'fill',
    paint: {
      'fill-color': {
        property: 'percentile',
        stops: [
          [0, '#3288bd'],
          [1, '#66c2a5'],
          [2, '#abdda4'],
          [3, '#e6f598'],
          [4, '#ffffbf'],
          [5, '#fee08b'],
          [6, '#fdae61'],
          [7, '#f46d43'],
          [8, '#d53e4f']
        ]
      },
      'fill-opacity': 0.8
    }
  };
// counties type fill
export const countiesLayer = {
  id: 'counties',
  type: 'fill',
  'source-layer': 'original',
  paint: {
    'fill-outline-color': 'rgba(0,0,0,0.1)',
    'fill-color': 'rgba(0,0,0,0.1)'
  }
};
// Highlighted county polygons
export const highlightLayer = {
  id: 'counties-highlighted',
  type: 'fill',
  source: 'counties',
  'source-layer': 'original',
  paint: {
    'fill-outline-color': '#484896',
    'fill-color': '#6e599f',
    'fill-opacity': 0.75
  }
};
