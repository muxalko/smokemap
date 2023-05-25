import { useLazyQuery, useQuery, useMutation } from "@apollo/client";
import { NOT_APPROVED_REQUESTS_QUERY, APPROVE_REQUEST } from "../src/graphql/queries/request";
import { useState, useEffect } from "react";

function RequestsList( { doRefresh, setRefresh }) {

  useEffect(() => {
    console.log("Component render: RequestsList");
  });

  // useEffect(() => {
  //   if (doRefresh) {
  //     console.log("Component refresh: RequestsList");
  //     getRequests();
  //     setRefresh(false)
  //   }
  // }, [doRefresh]);

  //console.log("NOT_APPROVED_REQUESTS_QUERY: " + JSON.stringify(NOT_APPROVED_REQUESTS_QUERY));
  
  //const { loading, error, data } = useQuery(NOT_APPROVED_REQUESTS_QUERY);
  const [getRequests, { called, data, loading, error }] = useLazyQuery(NOT_APPROVED_REQUESTS_QUERY);
  const [approveRequest, { error_approve, reset }] = useMutation(APPROVE_REQUEST);
  
  if (error) return <div>Error loading Requests.</div>;
  if (loading) return <div>Loading</div>;

  if (doRefresh) {
      console.log("RequestsList REFRESH");
      getRequests();
      setRefresh(false)
  }

  if (data) {
    const { requestsToApprove } = data;
    console.log("requestsToApprove", requestsToApprove)
    var requestslist = requestsToApprove.map(function(request){
      return(
         <li key={request.id}>
            <div>
              <p>{request.id}.{request.name}</p>
              <button onClick={() => onClickApproveHandler(request.id)}>Approve</button>
            </div>
          </li>
      )
    })
  } 

  function onClickApproveHandler(value) {
    approveRequest({ variables: { id: value, input: { approvedBy: 'UI', approvedComment: 'Testing approvals' } } })
    setRefresh(true);
  }

  function onClickGetRequests() {
    console.log("Clicked 'load requests' button");
    getRequests();
  }

  return (
    <>
      <button onClick={() => onClickGetRequests()}>load requests</button>
      <ul>{requestslist}</ul>;
      {
        error &&
        <LoginFailedMessageWindow
          message={error.message}
          onDismiss={() => console.log(error.message)}
        />
      }
      {
        error_approve &&
        <LoginFailedMessageWindow
          message={error_approve.message}
          onDismiss={() => reset()}
        />
      }
    </>
  );
}

export default RequestsList;