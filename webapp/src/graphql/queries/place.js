import { gql } from "@apollo/client";

export const ALL_PLACES_QUERY = gql`
query {
      places {
        id
        type
        geometry {
          type
          coordinates
        }
        bbox
        properties {
          name
        }
  }
}
`;

export const ADD_PLACE_QUERY = gql`
  mutation CreatePlace($name: String!, $location: Geometry!) {
    createPlace(name: $name, location: $location) {
      place {
        id
      }
    }
  }
`;

