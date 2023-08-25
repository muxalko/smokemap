import { useLazyQuery, useQuery, useMutation } from "@apollo/client";
import { NOT_APPROVED_REQUESTS_QUERY, APPROVE_REQUEST } from "../src/graphql/queries/request";
import { useState, useEffect } from "react";

function RequestsList( { doRefresh, setRefresh }) {

  
  const { loading, error, data, refetch } = useQuery(NOT_APPROVED_REQUESTS_QUERY, {
      //variables: { test },
      //pollInterval: 60000,
    });
  //const [getRequests, { useLazyQueryCalled, useLazyQueryData, useLazyQueryLoading, useLazyQueryError }] = useLazyQuery(NOT_APPROVED_REQUESTS_QUERY);
  const [approveRequest, { error_approve, reset }] = useMutation(APPROVE_REQUEST);
  

  // useEffect(() => {
  //   console.log("requestsList: useLazyQueryData watcher fired")
  //   if (useLazyQueryData) {
  //     const { requestsToApprove } = useLazyQueryData;
  //     console.log("DATA from useLazyQuery", requestsToApprove)
  //     var requestslist = requestsToApprove.map(function(request){
  //       return(
  //         <li key={request.id}>
  //             <div>
  //               <p>{request.id}.{request.name}</p>
  //               <button onClick={() => onClickApproveHandler(request.id)}>Approve</button>
  //             </div>
  //           </li>
  //       )
  //     })
  //   } 
  // },[useLazyQueryData]);

  useEffect(() => {
    console.log("Component render: RequestsList");
  });

  if (error) return <div>Error loading Requests.</div>;
  if (loading) return <div>Loading</div>;

  if (doRefresh) {
      console.log("RequestsList REFRESH");
      //refetch()
      setRefresh(false)
  }

  if (data) {
    const { requestsToApprove } = data;
    console.log("DATA from useQuery", requestsToApprove)
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
  
  // function onClickGetRequests() {
  //   console.log("Clicked 'load requests' button");
  //   getRequests();
  // }

  return (
    <>
      {/* <button onClick={() => onClickGetRequests()}>load requests</button> */}
      {/* <button onClick={() => refetch()}>refetch</button> */}
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