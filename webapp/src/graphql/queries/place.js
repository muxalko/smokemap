import { gql, useQuery } from "@apollo/client";

export const ALL_PLACES_QUERY = gql`
  query {
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
      imageurl
      dateCreated
      dateApproved
      approved
      category {
        id
        name
      }
      tags {
        id
        name
        category{
          id
          name
        }
      }
      __typename
    }
}
`;

export const ADD_PLACE_QUERY = gql`
  mutation CreateRequest($input: RequestInput!) {
  createRequest(input: $input) {
    request {
      id
      name
      description
    }
  }
}

{
  "input": {
    "name": "NightStar1",
    "description": "open all night",
    "address": "1 Baile Na Gleanna, Inisheer, Co. Galway, Ireland"
  }
}
`;