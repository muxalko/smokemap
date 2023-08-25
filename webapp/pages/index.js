import Head from "next/head";
import { useEffect, useState, useRef } from "react";
import { gql, useQuery, useLazyQuery } from "@apollo/client";
//import useSWR from "swr";

import { addDataLayer } from "../components/map/addDataLayer";
// import { initializeMap } from "../components/map/initializeMap";
import { fetcher } from "../utilities/fetcher";
//import PlacesList from "../components/placesLists";
import { ALL_PLACES_QUERY } from "../src/graphql/queries/place";

import styled from "styled-components";
import Modal from "../components/modal";

const maplibregl = require("maplibre-gl/dist/maplibre-gl.js");

export default function Home() {
  const [pageIsMounted, setPageIsMounted] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const [Map, setMap] = useState();
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const pointsLayerId = 'points';

  // static api example
  //const { data, error } = useSWR("/api/liveMusic", fetcher);
  // if (error) {
  //   console.error(error);
  // }
  
  const [places, setPlaces] = useState({});
  const [viewport, setViewport] = useState({
    width: '100%',
    height: '100%',
    latitude: 0,
    longitude: 0,
    zoom: 10,
  });



  //const { loading, error, pointsData } = useLazyQuery(ALL_PLACES_QUERY);
  //const { data: pointsData, isLoading } = useQuery(pointsLayerId, async () => {
  // const [
  //     getPlaces,
  //     { called, data, loading, error }
  //   ] = useLazyQuery(ALL_PLACES_QUERY, {
  //     variables: {
  //       name: 'The Pub',
  //     },
  //     fetchPolicy: 'network-only',
  //     onCompleted: (d) => setPlaces(d)
  //   });
  
  const [getPlaces, { called, data, loading, error }] = useLazyQuery(ALL_PLACES_QUERY);

  useEffect(() => {
    setPageIsMounted(true);
    
  //   let map = new maplibregl.Map({
  //     container: 'my-map',
  //     // Use a minimalist raster style
  //     style: {
  //         'version': 8,
  //         'name': 'Blank',
  //         'center': [0, 0],
  //         'zoom': 0,
  //         'sources': {
  //             'raster-tiles': {
  //                 'type': 'raster',
  //                 'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
  //                 'tileSize': 256,
  //                 'minzoom': 0,
  //                 'maxzoom': 19
  //             }
  //         },
  //         'layers': [
  //             {
  //                 'id': 'background',
  //                 'type': 'background',
  //                 'paint': {
  //                     'background-color': '#e0dfdf'
  //                 }
  //             },
  //             {
  //                 'id': 'simple-tiles',
  //                 'type': 'raster',
  //                 'source': 'raster-tiles'
  //             }
  //         ],
  //         'id': 'blank'
  //     },
  //     center: [13.40941680375606, 52.52082396407631],
  //     zoom: 15,
  //     pitch: 40,
  //     bearing: 0,
  //     antialias: true
  // });

    //initializeMap(maplibregl, map);
    // mapInstanceRef.current = map;

    
    
// map.on('load', function () {
//   // Add an image to use as a custom marker
//   map.loadImage('https://maplibre.org/maplibre-gl-js-docs/assets/custom_marker.png',
//       function (error, image) {
//           if (error) throw error;
//           map.addImage('custom-marker', image);

//           // Add a GeoJSON source with 3 points.
//           map.addSource(pointsLayerId, 
//             {
//               'type': 'geojson',
//               'data': {
//                 'type': 'FeatureCollection',
//                 'features': [
//                       {
//                         'type': 'Feature',
//                         'properties': {},
//                         'geometry': {
//                           'type': 'Point',
//                           'coordinates': [-91.395263671875,-0.9145729757782163]
//                         }
//                       },
//                       {
//                         'type': 'Feature',
//                         'properties': {},
//                         'geometry': {
//                         'type': 'Point',
//                         'coordinates': [-90.32958984375,-0.6344474832838974]
//                         }
//                       },
//                       {
//                         'type': 'Feature',
//                         'properties': {},
//                         'geometry': {
//                         'type': 'Point',
//                         'coordinates': [-91.34033203125,0.01647949196029245]
//                         }
//                       }
//                     ]
//                   }
//             }
//           );
   
//           // Add a symbol layer
//           map.addLayer(
//             {
//               'id': 'symbols',
//               'type': 'symbol',
//               'source': pointsLayerId,
//               'layout': {
//                   'icon-image': 'custom-marker'
//                 }
//             }
//           );
//       }
//   );
    const initializeMap = () => {
      const map = new maplibregl.Map({
        // container: 'myMap',
        container: mapContainerRef.current,
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

      mapInstanceRef.current = map;

      map.on('load', () => {

        console.log(JSON.stringify(places))
        console.log(JSON.stringify(data))

        // Create a new source for the points data
        map.addSource(pointsLayerId, {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: places || [], // Initially empty or populated with retrieved data
          },
        });

        // Add a layer for the points
        map.addLayer({
          id: pointsLayerId,
          source: pointsLayerId,
          type: 'circle',
          paint: {
            'circle-color': '#ff0000',
            'circle-radius': 6,
          },
        });
      }); //map on load function

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

      setMap(map);

      console.log("Map initialized")
    };

    initializeMap();

  }, []); //useEffect
    
  useEffect(() => {
    console.log("Execute getPlaces()")
    getPlaces()
  },[]);

  // useEffect(() => {
  //   // Fetch places data from the database
  //   const fetchPlaces = async () => {
  //     try {
  //       const response = await fetch('/api/places'); // Replace with your API endpoint
  //       const data = await response.json();
  //       setPlaces(data);
  //     } catch (error) {
  //       console.error('Error fetching places:', error);
  //     }
  //   };

  //   fetchPlaces();
    
  //   console.log(JSON.stringify(places))

   
  // }, []); 


  // useEffect(() => {
  //   if (pageIsMounted && data) {
     
  //     Map.on("load", function () {
  //       addDataLayer(Map, data);
  //     });
  //   }
  // }, [pageIsMounted, setMap, data, Map]);

  return (
    <Container>
      <Head>
        <title>Smokemap v0.1.0</title>
        <link rel="icon" href="/favicon.ico" />
        <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet" />
      </Head>
      
      {called && loading ? (
        <div>
          {error ? (
          <div>{error}</div>
          ) : (
            <div>{error}</div>
          )}
          <div>Please wait while the page is loading...</div>
        </div>
      ) : (
        <MapContainer ref={mapContainerRef} id="myMap" />
      )}
     

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
               <form action="/api/form" method="post">
                <label htmlFor="first">First name:</label>
                <input type="text" id="first" name="first" />
                <label htmlFor="last">Last name:</label>
                <input type="text" id="last" name="last" />
                <button type="submit">Submit</button>
              </form>
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
  //z-index: -10;
`

const Overlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  
  background-color: rgba(0,0,0,0.5); /*dim the background*/
`