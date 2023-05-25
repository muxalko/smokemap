import { gql, useQuery } from "@apollo/client";
import { ALL_PLACES_QUERY } from "../src/graphql/queries/place";
import { useEffect } from "react";

function PlacesList({onClickHandler}) {
  
  useEffect(() => {
    console.log("Component render: PlacesList");
  });

  const { loading, error, data } = useQuery(ALL_PLACES_QUERY);

  if (error) return <div>Error loading Places.</div>;
  if (loading) return <div>Loading</div>;

  const { places } = data;

  var placeslist = places.map(function(place){
    return (
      <li key={place.id}>
          <div>
            <p>{place.id}.{place.properties.name})</p>
            <button onClick={() => {onClickHandler(place.geometry.coordinates)}}>FlyTo</button>
          </div>
        </li>
    )
  })

  return <ul>{placeslist}</ul>;
}

export default PlacesList;