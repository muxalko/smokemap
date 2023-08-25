import * as React from 'react'

import {useState, useRef, useEffect, useMemo, useCallback} from 'react';
import useSwr from 'swr'
import Map, {Source, Layer} from 'react-map-gl/maplibre';

import ControlPanel from './control-panel_cities';
// TODO: investigate error when installing canvas - neeeded for SVG type of images
//import MarkerIconSvg from "./../src/assets/icon-marker.svg";
//import { Image } from "canvas";

import styled from "styled-components";
import {clusterLayer, clusterCountLayer, unclusteredPointLayer} from './layers';

//vacouver start
const lon = -123.11343223112543;
const lat = 49.28339038044595;


const fetcher = (...args) => fetch(...args).then((response) => response.json());

export default function App() {
    const mapRef = useRef();
    const map = mapRef.current
    
    // load custom icon symbol
    const loadImage = (name, icon) => {
      if (map && !map.hasImage(name)) {
        //NOTE This is really how are you load an SVG for mapbox
        //let img = new Image(24, 24);
        //img.crossOrigin = "Anonymous"; //it's not cross origin, but this quiets the canvas error
        //img.onload = () => {
        //  map.addImage("store-icon", img, { sdf: true });
        //};
        //img.src = MarkerIconSvg;

        //NOTE ref for adding local image instead
        map.loadImage(icon, (error, image) => {
          if (error || image === undefined) throw error;
          map.addImage(name, image, { sdf: false });
        });
      }
    };
    

    const onSelectCity = useCallback(({longitude, latitude}) => {
        mapRef.current?.flyTo({center: [longitude, latitude], duration: 2000});
      }, []);
    
    const onClick = event => {
        const feature = event?.features[0];
        const clusterId = feature && feature?.properties.cluster_id;
    
        const mapSource = mapRef.current.getSource('hydrants');
    
        mapSource && mapSource.getClusterExpansionZoom(clusterId, (err, zoom) => {
          if (err) {
            return;
          }
    
          feature && mapRef.current.easeTo({
            center: feature.geometry.coordinates,
            zoom,
            duration: 500
          });
        });
    };
    //const url = "http://192.168.56.5:7800/public.hydrants.json";
    const url = "http://192.168.56.5:9000/collections/public.hydrants/items?limit=-1";
    //const url = 'https://docs.mapbox.com/mapbox-gl-js/assets/earthquakes.geojson';
    const {data, error} = useSwr(url, fetcher) 
    //console.log(JSON.stringify(data));

    const hydrantsGeoJSON = useMemo(() => {
        return data
      }, [data]);

    const [viewport, setViewport] = useState({
        latitude: lat,
        longitude: lon,
        zoom: 11,
        bearing: 0,
        pitch: 0
    });


    const POINT_SOURCE = {
        type: "vector",
        tiles: [
          //  'http://192.168.56.5:7800/public.places_place/{z}/{x}/{y}.pbf',
           'http://192.168.56.5:7800/public.hydrants/{z}/{x}/{y}.pbf',
        ],
        minzoom: 0,
        maxzoom: 22,
      };
    
    // get bounds
    // const mapBounds = mapRef?.current && mapRef.current.getBounds().toArray().flat().join(',');
    // console.log(mapBounds)
    
    const EARTHQUAKES_SOURCE = {
       data: "http://192.168.56.5:9000/collections/public.hydrants/items?limit=-1&precision=5&properties="
       //data: "http://192.168.56.5:9000/collections/public.hydrants/items?limit=10000&bbox=" + ( mapBounds ? mapBounds : [lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1].join(',') )
        // data: "https://docs.mapbox.com/mapbox-gl-js/assets/earthquakes.geojson"
    }

    const POINT_STYLE_CIRCLE = {
        type: 'circle',
        paint: {
          'circle-radius': 10,
          'circle-color': '#007cbf'
        }
      };
    
    return  (
        <>
            <Map reuseMaps
            {...viewport}
            ref={mapRef}
            style={{width: '100vw', height: '100vh', display: 'flex'}}
  
            //mapStyle="https://demotiles.maplibre.org/style.json"
            mapStyle={"https://api.maptiler.com/maps/basic-v2/style.json?key="+process.env.NEXT_PUBLIC_MAPTILER_API_TOKEN}
            maxZoom={20}
            onMove={(evt) => {
                setViewport({...evt.viewState})
            }}
            interactiveLayerIds={[clusterLayer.id]}
            onClick={onClick}
            onLoad={() => {
                console.log("onLoad() fired")
                console.log(mapRef && mapRef.current ? mapRef.current.getStyle().sources : 'mapRef is null');
                loadImage("fire-hydrant", 'fire-hydrant.png');
            }}
            >
    
                <Source 
                    id='hydrants'
                    type='geojson'
                    cluster={true}
                    clusterMaxZoom={15}
                    clusterRadius={75}
                     {...EARTHQUAKES_SOURCE}>
                    
                    <Layer {...{source: 'hydrants', ...clusterLayer}} />
                    <Layer {...{source: 'hydrants', ...clusterCountLayer}} />
                    <Layer {...{source: 'hydrants', ...unclusteredPointLayer}} />
                        
                    {/* <Layer
                    {...{ //id: 'hydrants',
                        // source: 'hydrants',
                        "source-layer": "public.hydrants",
                        ...POINT_STYLE_CIRCLE,
                        // filter: categoryFilter,
                        // layout: {
                        //     visibility: searchString === "" ? "visible" : "none",
                        // },
                    }}
                    /> */}
                </Source>  
                {/* {hydrantsGeoJSON &&
                  <Source id="vehicles" type="geojson" data={hydrantsGeoJSON}>
                      <Layer type="symbol"
                          layout={{...hydrantLayout}} />
                  </Source>   
                } */}
            </Map>

            <ControlPanel onSelectCity={onSelectCity} />

        </>
    )
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