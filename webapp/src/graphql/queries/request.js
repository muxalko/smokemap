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
    }
}
`;

export const NOT_APPROVED_REQUESTS_QUERY = gql`
query {
	requestsToApprove {
        id
        name
        address {
          id
          address
          lat
          long
        }
        description
        dateCreated
        dateUpdated
        dateApproved
        approved
        approvedBy
        approvedComment
      }
}
`;


export const ADD_REQUEST = gql`
mutation CreateRequest($input: RequestInput!) {
    createRequest(input: $input) {
      request {
        id
        name
        address {
          id
          address
          lat
          long
        }
        description
        dateCreated
      }
    }
  }
`;

export const APPROVE_REQUEST = gql`
mutation ApproveRequest($id: ID!, $input: RequestApproveInput! ) {
    approveRequest(id: $id, input: $input) {
      request {
        id
        name
        address {
          id
          address
          lat
          long
        }
        description
        dateCreated
        dateUpdated
        dateApproved
        approved
        approvedBy
        approvedComment
      }
    }
  }
`;