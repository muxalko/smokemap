import React, { useState, useEffect, useContext, useRef } from 'react';
import { ThemeContext } from './ThemeContext';
import { themes } from './ThemeContext';
import { PlaceForm, CreateRequest } from '../components/form_place';
import ErrorBoundary from '../components/ErrorBoundary';
import { ListCategory, AddCategory } from '../components/category'
import PlacesList from '../components/placesLists';
//import Map from '../components/map/Map';
import styled from "styled-components";

import { gql, useQuery, useLazyQuery } from "@apollo/client";
import { ALL_PLACES_QUERY } from "../src/graphql/queries/place";

// import map script
const maplibregl = require("maplibre-gl/dist/maplibre-gl.js");

export default function About() {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const pointsLayerId = 'points';

  const [places, setPlaces] = useState([]);
  const [getPlaces, { called, data, loading, error }] = useLazyQuery(ALL_PLACES_QUERY);
  const [mymap, setMymap] = useState();

  useEffect(() => {
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
      center: [13.40941680375606, 52.52082396407631],
      zoom: 15,
      pitch: 40,
      bearing: 0,
      antialias: true
      });

      map.on('load', () => {
        
        console.log("map.onLoad() - init map with default values")

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

        mapInstanceRef.current = map;
        setMymap(map);

        console.log("Execute getPlaces()");
        getPlaces();

      }); //map on load function

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
      
      console.log("Map initialized")

    };

    initializeMap();

  }, []); //useEffect
  
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
    console.log("places changed: "+JSON.stringify(places));
    if (mymap) {
      console.log("Map instance found");
      console.log(mymap);
      try { 
        const isSourceLoaded = mymap.isSourceLoaded(pointsLayerId);
        if (isSourceLoaded) {
          console.log("'"+pointsLayerId+"' source is loaded.");
        } else {
          console.log("'"+pointsLayerId+"' source is not loaded yet.");
        }
        const isStyleLoaded = mymap.isStyleLoaded();
        if (isStyleLoaded) {
          console.log("Map style is loaded.");
        } else {
          console.log("Map style is not loaded yet.");
        }
        if (isStyleLoaded && isSourceLoaded) {
          console.log(" ... updating places");
          
          // const test_data = {
          //   // "type": 'geojson',
          //   // "data": {
          //     "type": 'FeatureCollection',
          //     "features": [
          //           { 
          //             "__typename":"PlaceType",
          //             "id":"1",
          //             "type":"Feature",
          //             "geometry": {
          //               "__typename":"GeometryObjectType",
          //               "type":"Point",
          //               "coordinates":[13.409408925100808,52.52082022204784]
          //               },
          //             "bbox":[13.409408925100808,52.52082022204784,13.409408925100808,52.52082022204784],
          //             "properties":{
          //               "__typename":"PlaceProperties",
          //               "name":"Alex"
          //               }
          //           }
          //         ]
          //     // },
          // }
          mymap.getSource(pointsLayerId).setData({
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
  },[places]);
  
  useEffect(() => {
    console.log("Just a little render :)");
  });

  // watch data changes
  useEffect(() => {
    if (data) {
      console.log("data changed: got called="+called+", loading="+loading+", error="+error)
      console.log("got data: "+JSON.stringify(data))
      setPlaces(data.places);
    }
  },[data]);

    return ( 
      <Container>
      {/* 
      <ErrorBoundary>
        <CreateRequest />
      </ErrorBoundary>
      <PlacesList /> 
     
      */}
 <MapContainer ref={mapContainerRef} />
{/*         
        {called && loading ? (
        <div>{error ? (
          <div>Error: {error}</div>
          ) : (
            <div>Please wait while the page is loading...</div>
          )}</div>
        ) : (<MapContainer ref={mapContainerRef} />)} */}

    </Container>
   
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

const Overlay = styled.div`
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  
  background-color: rgba(0,0,0,0.5); /*dim the background*/
`


// example counter
function Counter() {
  const [count, setCount] = useState(0);

  function handleClick() {
    setCount(count + 1);
  }

  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={handleClick}>Increment</button>
    </div>
  );
}

// example data fetch from api route
function DataFetcher() {
  const [data, setData] = useState([]);

  useEffect(() => {
    async function fetchData() {
      const response = await fetch('api/listNames');
      const json = await response.json();
      console.log(json)
      setData(json);
    }

    fetchData();
  }, []);

  return (
    <ul>
      {data.map((item) => (
        <li key={item.id}>{item.name}</li>
      ))}
    </ul>
  );
}

// example theme switch
function ThemedButton(props) {
  const theme = useContext(ThemeContext);

  return (
    <button
    // follow https://www.learnhowtoprogram.com/react/react-with-apis/help-queue-creating-a-context-and-provider
      // style={{ background: theme.background, color: theme.foreground }}
      style={{ background: 'blue', color: 'white' }}
      {...props}
    />
  );
}

// example tesx input
function TextInput() {
  const inputRef = useRef(null);

  function handleClick() {
    inputRef.current.focus();
  }

  return (
    <div>
      <input type="text" ref={inputRef} />
      <button onClick={handleClick}>Focus</button>
    </div>
  );
}
