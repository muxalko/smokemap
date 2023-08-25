import React, { useState, useEffect, useContext, useRef } from 'react';
import { gql, useQuery, useLazyQuery } from "@apollo/client";
import { ALL_PLACES_QUERY } from "../src/graphql/queries/place";
import styled from "styled-components";
import MaplibreGeocoder from '@maplibre/maplibre-gl-geocoder';
import '@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css';

// Functions should return Carmen GeoJSON https://github.com/mapbox/carmen/blob/master/carmen-geojson.md
// View config definitions in our [documentation](https://github.com/maplibre/maplibre-gl-geocoder/blob/master/API.md#setgeocoderapi)
// var Geo = {
//   forwardGeocode: async (config) => { /* definition here */ },
//   reverseGeocode: async (config) => { /* definition here */ }, // optional reverse geocoding API
//   getSuggestions: async (config) => { /* definition here */ } // optional suggestion API
// };

// import map script
const maplibregl = require("maplibre-gl/dist/maplibre-gl.js");

// Pass in or define a geocoding API that matches the above
// const geocoder = new MaplibreGeocoder(Geo, { mapboxgl: maplibregl });


export default function Map({ flyTo }) {

    const mapContainerRef = useRef(null);
    const mapInstanceRef = useRef(null);
    const pointsLayerId = 'points';

    const [pageIsMounted, setPageIsMounted] = useState(false);

    const [places, setPlaces] = useState([]);
    const { useQueryData, useQueryLoading, useQueryError } = useQuery(ALL_PLACES_QUERY);
    const [getPlaces, { called, data, loading, error }] = useLazyQuery(ALL_PLACES_QUERY);
    const [mapRef, setMapRef] = useState();
    // const [focusOn, setFocusOn] = useState(flyTo);


    useEffect(() => {
        setPageIsMounted(true);
        
        console.log("Map is mounted.")

        if (mapInstanceRef.current) {
        console.log("Map instance already exists, bypass initialization.");
        return; //stops map from intializing more than once
        }

        const initializeMap = () => {
            const map = new maplibregl.Map({
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
                center: [52.51965492668956, 13.406841854355584],
                zoom: 15,
                pitch: 40,
                bearing: 0,
                antialias: true
            });

            map.on('load', () => {
                console.log("map.onLoad(): started");
                // var geocoder_api = {
                //     forwardGeocode: async (config) => {
                //         const features = [];
                //         try {
                //             let request =
                //             'https://nominatim.openstreetmap.org/search?q=' +
                //                 config.query +
                //                 '&format=geojson&polygon_geojson=1&addressdetails=1';

                //             const response = await fetch(request);
                            
                //             const geojson = await response.json();
                            
                //             for (let feature of geojson.features) {
                //                 let center = [
                //                     feature.bbox[0] + (feature.bbox[2] - feature.bbox[0]) / 2,
                //                     feature.bbox[1] + (feature.bbox[3] - feature.bbox[1]) / 2
                //                 ];

                //                 let point = {
                //                     type: 'Feature',
                //                     geometry: {
                //                         type: 'Point',
                //                         coordinates: center
                //                     },
                //                     place_name: feature.properties.display_name,
                //                     properties: feature.properties,
                //                     text: feature.properties.display_name,
                //                     place_type: ['place'],
                //                     center: center
                //                 };

                //                 features.push(point);
                //             }

                //         } catch (e) {
                //             console.error(`Failed to forwardGeocode with error: ${e}`);
                //         }
                            
                //         return {
                //             features: features
                //         };
                //     }
                // };

                // map.addControl(
                //     new MaplibreGeocoder(geocoder_api, {
                //         maplibregl: maplibregl
                //     })
                // );            
                    
                // Create a new source for the points data
                map.addSource(pointsLayerId, {
                    type: 'geojson',
                    data: {
                        type: 'FeatureCollection',
                        features: places || [], // Initially empty or populated with retrieved data
                    },
                });
                console.log("map.onLoad(): addSource("+pointsLayerId+")");

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
                console.log("map.onLoad(): addLayer("+pointsLayerId+")");
                
                mapInstanceRef.current = map;
                setMapRef(map);
                console.log("map.onLoad(): mapRef is "+JSON.stringify(mapRef));
                
                flyToPoint()
                console.log("map.onLoad(): flyToPoint "+JSON.stringify(flyTo));

                //console.log("Execute getPlaces()");
                //getPlaces();

                console.log("map.onLoad(): ended")
            }); //map on load function

            map.on('style.load', () => {  
                console.log("map.onStyleLoad(): fired")
                console.log("map.onStyleLoad(): mapRef is "+JSON.stringify(mapRef));
            }); //map on style.load function

            // fires each time map is idle
            // map.on('idle', () => { 
            //     console.log("map.onIdle()")
            // }); //map on idle function

        

            // Center the map on the coordinates of any clicked symbol from the 'symbols' layer.
            map.on('click', pointsLayerId, function (e) {
                map.flyTo({
                center: e.features[0].geometry.coordinates
                });
            }); 
            
            // Change the cursor to a pointer when the it enters a feature in the 'symbols' layer.
            map.on('mouseenter', pointsLayerId, function () {
                map.getCanvas().style.cursor = 'pointer';
            });
            
            // Change it back to a pointer when it leaves.
            map.on('mouseleave', pointsLayerId, function () {
                map.getCanvas().style.cursor = '';
            });


            //mapInstanceRef.current = map;
            
            

            };

        initializeMap();

    }, []);
    
    // get async from api route 
    // useEffect(() => {
    //   // Fetch places data from the database
    //   const fetchPlaces = async () => {
    //     try {
    //       const response = await fetch('/api/places'); // Replace with your API endpoint
    //       const data = await response.json();
    //       console.log("data: "+JSON.stringify(data))
    //       // enqueue places update 
    //       setPlaces(data);
    //     } catch (error) {
    //       console.error('Error fetching places:', error);
    //     }
    //   };
    //   fetchPlaces();
    // }, []); 

    // useEffect(() => {
    //   console.log("Execute getPlaces()");
    //   getPlaces();
    // },[]);

    useEffect(() => {
        if (pageIsMounted && places) { 
        console.log("places changed: "+JSON.stringify(places));
        if (mapRef) {
            console.log("Map instance found");
            console.log(mapRef);
            try { 
            const isSourceLoaded = mapRef.isSourceLoaded(pointsLayerId);
            if (isSourceLoaded) {
                console.log("'"+pointsLayerId+"' source is loaded.");
            } else {
                console.log("'"+pointsLayerId+"' source is not loaded yet.");
            }
            const isStyleLoaded = mapRef.isStyleLoaded();
            if (isStyleLoaded) {
                console.log("Map style is loaded.");
            } else {
                console.log("Map style is not loaded yet.");
            }
            if (isStyleLoaded && isSourceLoaded) {
                console.log(" ... updating places");
                
                mapRef.getSource(pointsLayerId).setData({
                    type: 'FeatureCollection',
                    features: places || [], // empty or populated with retrieved data
                });

            }
            
            } catch (error) {
            console.log("Cannot get source inside map instance: " + error);
            }
        } else {
            console.log("Cannot get reference to map instance.");
        }
        }
    },[places]);
    
     // watch data changes - query places result from useLazyQuery
     useEffect(() => {
        console.log("useEffect(useQueryData): useQuery watcher.");
        if (useQueryData) {
        console.log("data changed: got useQueryLoading="+useQueryLoading+", useQueryError="+useQueryError)
        console.log("got data: "+JSON.stringify(data))
        setPlaces(useQueryData.places);
        }
    },[useQueryData]);

    // watch data changes - query places result from useLazyQuery
    useEffect(() => {
        console.log("useEffect(data): useLazyQuery watcher.");
        if (data) {
        console.log("data changed: got called="+called+", loading="+loading+", error="+error)
        console.log("got data: "+JSON.stringify(data))
        setPlaces(data.places);
        }
    },[data]);

    // fly to a point
    function flyToPoint() {
        if (mapRef && flyTo) {
            console.log("flying to: "+JSON.stringify(flyTo))
            mapRef.flyTo({
                center: flyTo
            });
        //console.log("Execute getPlaces() after a new request.");
        //getPlaces();
        } else {
            console.log("Cannot fly ;(");
        }
    }

    return (<MapContainer ref={mapContainerRef} />
        // <>
        //     {called && loading ? (
        //     <div>
        //         {error ? (
        //         <div>Error: {error}</div>
        //         ) : (
        //             <div>Please wait while the page is loading...</div>
        //         )}
        //     </div>
        //     ) : (<MapContainer ref={mapContainerRef} />)}
        // </>
    )
}

const MapContainer = styled.div`
  position: relative; 
  top: 0; 
  bottom: 0; 
  width: 100%;
  height: 100vh;
  //z-index: -10;
`

