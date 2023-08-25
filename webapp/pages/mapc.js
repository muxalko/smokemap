import * as React from 'react';
import {useState, useMemo, useCallback} from 'react';
import Map, {Popup, Source, Layer} from 'react-map-gl/maplibre';

import ControlPanel from './control-panel';

import {pointLayerStyle, countiesLayer, highlightLayer} from './map-style';

// A circle of 5 mile radius of the Empire State Building
const lon = -74.0122106;
const lat = 40.7467898;
//const GEOFENCE = turf.circle([lon, lat], 5, {units: 'miles'});

export default function App() {
  
  
  const [hoverInfo, setHoverInfo] = useState(null);
  
  const onHover = useCallback(event => {
    const county = event.features && event.features[0];
    setHoverInfo({
      longitude: event.lngLat.lng,
      latitude: event.lngLat.lat,
      countyName: county && county.properties.COUNTY
    });
  }, []); 
  
  const selectedCounty = (hoverInfo && hoverInfo.countyName) || '';
  const filter = useMemo(() => ['in', 'COUNTY', selectedCounty], [selectedCounty]);


  return (
    <>
        <Map
        initialViewState={{
            latitude: lat,
            longitude: lon,
            zoom: 3,
        }}
        minZoom={2}
        mapStyle="https://demotiles.maplibre.org/style.json"
        //onMouseMove={onHover}
        interactiveLayerIds={['counties']}
        >
        <Source type="vector" url="http://192.168.56.5:7800/public.places_place/{z}/{x}/{y}.pbf">
            <Layer {...pointLayerStyle} />
            {/* <Layer beforeId="waterway-label" {...countiesLayer} />
            <Layer beforeId="waterway-label" {...highlightLayer} filter={filter} /> */}
        </Source>
        {selectedCounty && (
        <Popup
            longitude={hoverInfo.longitude}
            latitude={hoverInfo.latitude}
            offset={[0, -10]}
            closeButton={false}
            className="county-info"
        >
            {selectedCounty}
        </Popup>
        )}
        </Map>
        <ControlPanel />
    </>
  );
}