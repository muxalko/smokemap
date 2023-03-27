import { gql, useQuery } from "@apollo/client";
import { ALL_PLACES_QUERY } from "../src/graphql/queries/place";

// export const ALL_PLACES_QUERY = gql`
//   query {
//     books {
//       id
//       title
//       isbn
//     }
//   }
// `;

function PlacesList() {
  const { loading, error, data } = useQuery(ALL_PLACES_QUERY);

  if (error) return <div>Error loading Places.</div>;
  if (loading) return <div>Loading</div>;

  const { requests } = data;

  console.log("requests", requests)

  var placeslist = requests.map(function(place){
    return <li key={place.id}>{place.id}.{place.name} - {place.address.address}</li>
  })


  return <ul>{placeslist}</ul>;
}

export default PlacesList;