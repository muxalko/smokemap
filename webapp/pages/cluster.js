import * as React from 'react'

import {useState, useRef, useCallback} from 'react';

import Map, {Source, Layer, AttributionControl, FullscreenControl} from 'react-map-gl/maplibre';

import ControlPanel from './../components/control-panel_cities';
// TODO: investigate error when installing canvas - neeeded for SVG type of images
//import MarkerIconSvg from "./../src/assets/icon-marker.svg";
//import { Image } from "canvas";

import {clusterLayer, clusterCountLayer, unclusteredPointLayer} from './../components/layers';

//vacouver start
const lon = -123.11343223112543;
const lat = 49.28339038044595;

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

    const [viewport, setViewport] = useState({
        latitude: lat,
        longitude: lon,
        zoom: 11,
        bearing: 0,
        pitch: 0
    });

    const EARTHQUAKES_SOURCE = {
       //data: process.env.NEXT_PUBLIC_FEATURESERV_ENDPOINT + "/collections/public.hydrants/items?limit=-1&precision=5&properties=name,status"
       data: process.env.NEXT_PUBLIC_FEATURESERV_ENDPOINT
       // data: "http://192.168.56.5:9000/collections/public.hydrants/items?limit=10000&bbox=" + ( mapBounds ? mapBounds : [lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1].join(',') )
        // data: "https://docs.mapbox.com/mapbox-gl-js/assets/earthquakes.geojson"
    }

   
    return  (
        <>
            <Map reuseMaps
            {...viewport}
            ref={mapRef}
            style={{width: '100vw', height: '100vh', display: 'flex'}}
  
            //mapStyle={process.env.NEXT_PUBLIC_MAP_STYLE}
            //mapStyle="https://demotiles.maplibre.org/style.json"
            mapStyle={"https://api.maptiler.com/maps/basic-v2/style.json?key=WJYHMjM1keLxRakXKZGa"}
            //mapStyle={process.env.NEXT_PUBLIC_MAPTILER_API_TOKEN ? "https://api.maptiler.com/maps/basic-v2/style.json?key="+process.env.NEXT_PUBLIC_MAPTILER_API_TOKEN:process.env.NEXT_PUBLIC_MAP_STYLE}
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
            // disable the default attribution
            attributionControl={false}
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
                        
                </Source>
                {/*need according to https://documentation.maptiler.com/hc/en-us/articles/4405445885457-How-to-add-MapTiler-attribution-to-a-map*/}
                <FullscreenControl />
                <AttributionControl
                  style={{
                   //color: 'ff7c92',
                    '-webkit-text-size-adjust': '100%',
                    '-webkit-tap-highlight-color': 'rgb(0 0 0/0)',
                    font: '12px/20px Helvetica Neue,Arial,Helvetica,sans-serif',
                    'box-sizing': 'border-box',
                    //'pointer-events': 'none',
                    position: 'absolute',
                    'z-index': '2',
                    bottom: '0',
                    right: '0',
                    'background-color': 'hsla(0,0%,100%,.5)',
                    margin: '0',
                    padding: '0 5px'
                  }} 
                  //customAttribution='<a href="https://www.maptiler.com"><img src="https://api.maptiler.com/resources/logo.svg" alt="MapTiler logo"></a>'
                  />
                {/* <AttributionControl
                  style={{position: 'absolute', left: '10px', bottom: '10px', "z-index": '999'}}
                  customAttribution='<a href="https://www.maptiler.com"><img src="https://api.maptiler.com/resources/logo.svg" alt="MapTiler logo"></a>
                                     <a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a>
                                     <a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>' /> */}
            </Map>

            <ControlPanel onSelectCity={onSelectCity} />
        </>
    )
}
