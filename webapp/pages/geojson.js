import * as React from 'react';
import {useState, useEffect, useMemo, useCallback} from 'react';

import Map, {Source, Layer} from 'react-map-gl/maplibre';
import ControlPanel from './control-panel';

import styled from "styled-components";

import {dataLayer} from './map-style';
import {updatePercentiles} from './utils';

// const MAPBOX_TOKEN = ''; // Set your mapbox token here

export default function App() {
  const [year, setYear] = useState(2015);
  const [allData, setAllData] = useState(null);
  const [hoverInfo, setHoverInfo] = useState(null);

  useEffect(() => {
    /* global fetch */
    fetch(
      'https://raw.githubusercontent.com/uber/react-map-gl/master/examples/.data/us-income.geojson'
    )
      .then(resp => resp.json())
      .then(json => setAllData(json))
      .catch(err => console.error('Could not load data', err)); // eslint-disable-line
  }, []);

  const onHover = useCallback(event => {
    const {
      features,
      point: {x, y}
    } = event;
    const hoveredFeature = features && features[0];

    // prettier-ignore
    setHoverInfo(hoveredFeature && {feature: hoveredFeature, x, y});
  }, []);

  const data = useMemo(() => {
    return allData && updatePercentiles(allData, f => f.properties.income[year]);
  }, [allData, year]);

  return (
    <>
        <Container>
            <MapContainer>
                <Map
                    initialViewState={{
                    latitude: 40,
                    longitude: -100,
                    zoom: 3
                    }}
                    mapStyle="https://demotiles.maplibre.org/style.json"
                    // mapboxAccessToken={MAPBOX_TOKEN}
                    interactiveLayerIds={['data']}
                    onMouseMove={onHover}
                >
                    <Source type="geojson" data={data}>
                        <Layer {...dataLayer} />
                    </Source>
                    {hoverInfo && (
                    <Tooltip style={{left: hoverInfo.x, top: hoverInfo.y}}>
                        <div>State: {hoverInfo.feature.properties.name}</div>
                        <div>Median Household Income: {hoverInfo.feature.properties.value}</div>
                        <div>Percentile: {(hoverInfo.feature.properties.percentile / 8) * 100}</div>
                    </Tooltip>
                    )}
                </Map>
            </MapContainer>
            <ControlPanelContainer>
                <ControlPanel year={year} onChange={value => setYear(value)} />
            </ControlPanelContainer>
        </Container>
    </>
  );
}

const Container = styled.div`
  height: 100vh;
  width: 100%;
  display: flex;
`

const MapContainer = styled.div`
  position: absolute; 
  top: 0; 
  bottom: 0; 
  width: 100%;
  //z-index: -10;
`
const ControlPanelContainer = styled.div`
    position: absolute;
    top: 0;
    right: 0;
    max-width: 320px;
    background: #fff;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
    padding: 12px 24px;
    margin: 20px;
    font-size: 13px;
    line-height: 2;
    color: #6b6b76;
    text-transform: uppercase;
    outline: none;
`
const Tooltip = styled.div`
    position: absolute;
    margin: 8px;
    padding: 4px;
    background: rgba(0, 0, 0, 0.8);
    color: #fff;
    max-width: 300px;
    font-size: 10px;
    z-index: 9;
    pointer-events: none;
`