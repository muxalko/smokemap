export const clusterLayer = {
  id: 'clusters',
  type: 'circle',
  filter: ['has', 'point_count'],
  paint: {
    'circle-color': ['step', ['get', 'point_count'], '#51bbd6', 100, '#f1f075', 750, '#f28cb1'],
    'circle-radius': ['step', ['get', 'point_count'], 20, 100, 30, 750, 40]
  }
};

export const clusterCountLayer = {
  id: 'cluster-count',
  type: 'symbol',
  filter: ['has', 'point_count'],
  layout: {
    'text-field': '{point_count_abbreviated}',
    'text-font': ['DIN Offc Pro Medium', 'Arial Unicode MS Bold'],
    'text-size': 12
  }
};

// export const unclusteredPointLayer = {
//   id: 'unclustered-point',
//   type: 'circle',
//   filter: ['!', ['has', 'point_count']],
//   paint: {
//     'circle-color': '#11b4da',
//     'circle-radius': 4,
//     'circle-stroke-width': 1,
//     'circle-stroke-color': '#fff'
//   }
// }

const hydrantLayout = {
  'icon-image': 'fire-hydrant',
  'icon-allow-overlap': true,
  'icon-size': 0.1,
  'text-field': ['get', 'status'],
  'icon-anchor': 'bottom', 
  'icon-offset': [0, -15],
  'text-anchor': 'top'
};

export const unclusteredPointLayer = {
  id: 'unclustered-point',
  type: 'symbol',
  filter: ['!', ['has', 'point_count']],
  layout: {...hydrantLayout}
}

