import { gql } from "@apollo/client";

export const ALL_REQUESTS_QUERY = gql`
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
      #imageurl
      #dateCreated
      #dateApproved
      #approved
      #category {
      #  id
      #  name
      #}
      #tags {
      #  id
      #  name
      #  category{
      #    id
      #    name
      #  }
      #}
      #__typename
    }
}
`;

export const ADD_REQUEST_QUERY = gql`
  mutation CreateRequest($input: RequestInput!) {
  createRequest(input: $input) {
    request {
      id
      name
      description
    }
  }
}
`;