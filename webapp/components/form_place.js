
import React, { useState, useCallback, useEffect } from 'react';
import { gql, useMutation } from '@apollo/client';
import { ADD_REQUEST } from '../src/graphql/queries/request'
import styled, { css } from 'styled-components'

import RequestsList from '../components/requestsList';

export function CreateRequest({ onSuccessfulCreation }) {

  const [refresh, setRefresh] = useState(false);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [address, setAddress] = useState('');

  const [submission_error, setSubmissionError] = useState(null);
  const [submission_result, setSubmissionResult] = useState(null)
  
  const [createRequest, { data, loading, error }] = useMutation(ADD_REQUEST , {
      onError: (error) => {
        // Handle the error here
        console.error('GraphQL Error:', error);
        // Update the form state or display an error message
        setSubmissionError(error); // Update the error state
      },
      onCompleted: (data) => {
        console.log("CreateRequest() completed with: " + JSON.stringify(data))
        setSubmissionResult(data.createRequest.request);
      },
    }
  );

  const handleSubmit = useCallback((event) => {
    event.preventDefault();

    //console.log(this.inputNode.value)

     // Get data from the form.
     const form_data = {
      name: event.target.name.value,
      description: event.target.description.value,
      addressString: event.target.address.value
    }
    //console.log("CreateRequest handleSubmit event.target: " + JSON.stringify(event.target))
    console.log("CreateRequest form_data: " + JSON.stringify(form_data))

    setSubmislssionError(null); // Reset the error state before making the mutation
    setSubmissionResult(null);

    createRequest({ variables: { input: form_data } });

    // if (loading) return 'Submitting...';
    // if (graphql_error) return `Submission error! ${error.message}`;
  });

  useEffect(() => {
    if (submission_result) {
      console.log("submission_result: "+JSON.stringify(submission_result));
      onSuccessfulCreation([submission_result.address.long, submission_result.address.lat]);
      setRefresh(true);
    }
  },[submission_result]);

  const handleNameChange = useCallback((event) => {
    setName(event.target.value);
  }, []);
  const handleDescriptionChange = useCallback((event) => {
    setDescription(event.target.value);
  }, []);
  const handleAddressChange = useCallback((event) => {
    setAddress(event.target.value);
  }, []);

  return (
    <>
    <PlaceFormContainer onSubmit={handleSubmit}>
    <FormGroup>
      <Label>Name:</Label>
      <Input type="text" name='name' value={name} onChange={handleNameChange} />
      <Label>Description:</Label>
      <Input type="text" name='description' value={description} onChange={handleDescriptionChange} />
      <Label>Address:</Label>
      <Input type="text" name='address' value={address} onChange={handleAddressChange} />
    </FormGroup>
    
    <Button type="submit">Submit</Button>
    </PlaceFormContainer>
    <div>
     {submission_result && (
     <Feedback type="success">Success! Place created with ID: {submission_result.id}, Name: {submission_result.name}, Address: {submission_result.address.address} {submission_result.address.lat},{submission_result.address.long}</Feedback>
    )}
    {submission_error ? 
    <Feedback type="error">Oh no! {submission_error.message}</Feedback> : null}
    {data && data.createRequest ? <Feedback type="success">Saved!</Feedback> : null}
    </div>
    <h4>Requests</h4>
    <RequestsList doRefresh={refresh} setRefresh={() => setRefresh()}/> 
    </>
  );
}

const PlaceFormContainer = styled.form`
  margin-bottom: 20px;
`;

const FormGroup = styled.div`
  margin-bottom: 15px;
`;

const Label = styled.label`
  display: block;
  margin-bottom: 5px;
  font-weight: bold;
  color: black;
`;

const Input = styled.input`
  width: 100%;
  padding: 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
`;

const Select = styled.select`
  width: 100%;
  padding: 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
`;

const Button = styled.button`
  padding: 10px 20px;
  background-color: #007bff;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;

  &:hover {
    background-color: #0056b3;
  }
`;

const Feedback = styled.div`
  padding: 10px;
  border-radius: 4px;
  font-weight: bold;

  /* Success styles */
  ${({ type }) =>
    type === 'success' &&
    css`
      background-color: #dff0d8;
      color: #3c763d;
      border: 1px solid #d6e9c6;
    `}

  /* Error styles */
  ${({ type }) =>
    type === 'error' &&
    css`
      background-color: #f8d7da;
      color: #721c24;
      border: 1px solid #f5c6cb;
    `}
`;