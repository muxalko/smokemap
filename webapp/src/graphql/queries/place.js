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