import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import { useQuery, gql } from '@apollo/client';

const MAPBOX_ACCESS_TOKEN = 'YOUR_MAPBOX_ACCESS_TOKEN';
const GRAPHQL_ENDPOINT = 'YOUR_GRAPHQL_ENDPOINT';
const pointsLayerId = 'points';

// represents a map class
const Map = () => {
  
  const mapInstanceRef = useRef(null);

  const { data: { points } = {}, loading } = useQuery(
    gql`
      query GetPoints {
          requests {
          id
          name
          address {
            id
            address
            lat
            long
          }
          description
        }
      }
    `,
    {
      fetchPolicy: 'cache-and-network',
    }
  );

  useEffect(() => {
    const initializeMap = () => {
      const map = new maplibregl.Map({
        container: 'map',
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
        // Create a new source for the points data
        map.addSource(pointsLayerId, {
          type: 'geojson',
          data: {
            type: 'FeatureCollection',
            features: points || [], // Initially empty or populated with retrieved data
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
      });
    };

    initializeMap();
  }, [points]);

  return (
    <div>
      {loading ? (
        <div>Loading...</div>
      ) : (
        <div id="map" style={{ width: '100%', height: '100%' }} />
      )}
    </div>
  );
};

export default Map;
