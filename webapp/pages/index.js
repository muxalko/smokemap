import Head from "next/head";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { addDataLayer } from "../components/map/addDataLayer";
import { initializeMap } from "../components/map/initializeMap";
import { fetcher } from "../utilities/fetcher";
import PlacesList from "../components/placesLists";
import styled from "styled-components";
import Modal from "../components/modal";

const maplibregl = require("maplibre-gl/dist/maplibre-gl.js");

export default function Home() {
  const [pageIsMounted, setPageIsMounted] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const [Map, setMap] = useState();
  const { data, error } = useSWR("/api/liveMusic", fetcher);

  if (error) {
    console.error(error);
  }

  useEffect(() => {
    setPageIsMounted(true);

    let map = new maplibregl.Map({
      container: 'my-map',
      // Use a minimalist raster style
      style: {
          'version': 8,
          'name': 'Blank',
          'center': [0, 0],
          'zoom': 0,
          'sources': {
              'raster-tiles': {
                  'type': 'raster',
                  'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                  'tileSize': 256,
                  'minzoom': 0,
                  'maxzoom': 19
              }
          },
          'layers': [
              {
                  'id': 'background',
                  'type': 'background',
                  'paint': {
                      'background-color': '#e0dfdf'
                  }
              },
              {
                  'id': 'simple-tiles',
                  'type': 'raster',
                  'source': 'raster-tiles'
              }
          ],
          'id': 'blank'
      },
      center: [13.40941680375606, 52.52082396407631],
      zoom: 15,
      pitch: 40,
      bearing: 0,
      antialias: true
  });

    //initializeMap(maplibregl, map);
    //setMap(map);
    
map.on('load', function () {
  // Add an image to use as a custom marker
  map.loadImage(
  'https://maplibre.org/maplibre-gl-js-docs/assets/custom_marker.png',
  function (error, image) {
  if (error) throw error;
  map.addImage('custom-marker', image);
  // Add a GeoJSON source with 3 points.
  map.addSource('points', {
  'type': 'geojson',
  'data': {
  'type': 'FeatureCollection',
  'features': [
  {
  'type': 'Feature',
  'properties': {},
  'geometry': {
  'type': 'Point',
  'coordinates': [
  -91.395263671875,
  -0.9145729757782163
  ]
  }
  },
  {
  'type': 'Feature',
  'properties': {},
  'geometry': {
  'type': 'Point',
  'coordinates': [
  -90.32958984375,
  -0.6344474832838974
  ]
  }
  },
  {
  'type': 'Feature',
  'properties': {},
  'geometry': {
  'type': 'Point',
  'coordinates': [
  -91.34033203125,
  0.01647949196029245
  ]
  }
  }
  ]
  }
  });
   
  // Add a symbol layer
  map.addLayer({
  'id': 'symbols',
  'type': 'symbol',
  'source': 'points',
  'layout': {
      'icon-image': 'custom-marker'
    }
  });
  }
  );
   
    // Center the map on the coordinates of any clicked symbol from the 'symbols' layer.
    map.on('click', 'symbols', function (e) {
      map.flyTo({
        center: e.features[0].geometry.coordinates
      });
    });
   
    // Change the cursor to a pointer when the it enters a feature in the 'symbols' layer.
    map.on('mouseenter', 'symbols', function () {
      map.getCanvas().style.cursor = 'pointer';
    });
    
    // Change it back to a pointer when it leaves.
    map.on('mouseleave', 'symbols', function () {
      map.getCanvas().style.cursor = '';
    });
  });
    
  }, []);

  
  useEffect(() => {
    if (pageIsMounted && data) {
     
      Map.on("load", function () {
        addDataLayer(Map, data);
      });
    }
  }, [pageIsMounted, setMap, data, Map]);

  return (
    <Container>
      <Head>
        <title>Smokemap v0.1.0</title>
        <link rel="icon" href="/favicon.ico" />
        <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet" />
      </Head>
   
      
      <MapContainer id="my-map" />

      <div id="modal-root"></div>
      
      {/* <Overlay>
        <PlacesList />
       </Overlay> */}

        <div>
            <button onClick={() => setShowModal(true)}>Open Modal</button>
            {showModal && <Modal
                onClose={() => setShowModal(false)}
                show={showModal}
            >
                Hello from the modal!
            </Modal>}
        </div>
      
    </Container>
    

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
  z-index: -10;
`

const Overlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  
  background-color: rgba(0,0,0,0.5); /*dim the background*/
`