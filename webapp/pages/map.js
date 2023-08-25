import * as React from 'react';
// import Map from 'react-map-gl/maplibre';
import Map, {Source, Layer} from 'react-map-gl/maplibre';
// import {CircleLayer} from 'react-map-gl/maplibre';
// import {FeatureCollection} from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';

import * as turf from '@turf/turf';

// A circle of 5 mile radius of the Empire State Building
const lon = -74.0122106;
const lat = 40.7467898;
const GEOFENCE = turf.circle([lon, lat], 5, {units: 'miles'});


const geojson = {
  type: 'FeatureCollection',
  features: [
    {type: 'Feature', geometry: {type: 'Point', coordinates: [lon, lat]}}
  ]
};

const layerStyle = {
  id: 'point',
  type: 'circle',
  paint: {
    'circle-radius': 10,
    'circle-color': '#007cbf'
  }
};


export default function App() {
  
  const [viewState, setViewState] = React.useState({
    longitude: lon,
    latitude: lat,
    zoom: 10
  });

  const onMove = React.useCallback(({viewState}) => {
    const newCenter = [viewState.longitude, viewState.latitude];
    // Only update the view state if the center is inside the 
    const inside = turf.booleanPointInPolygon(newCenter, GEOFENCE)
    console.log("onMove(): booleanPointInPolygon("+newCenter+","+JSON.stringify(GEOFENCE)+") = "+inside)
    if (inside) {
      setViewState(newCenter);
    }
  }, [])

  return (
    <Map
      {...viewState}
      //initialViewState={{...viewState}}
      style={{  height: '100vh', width: '100%', display: 'flex' }}
      // mapStyle="https://demotiles.maplibre.org/style.json"
      onMove={onMove}
      // onMove={evt => {
      //   console.log("onMove(): fired")
      //   setViewState(evt.viewState)}
      // } 
    >
       <Source
          id="hydrants" 
          type="vector" 
          //  data={geojson}
          data="http://192.168.56.5:7800/public.hydrants/{z}/{x}/{y}.pbf"
         
         >
        <Layer {...layerStyle} />
      </Source>
    </Map>
  );
}