
import React, { useState, useCallback } from 'react';
import { gql, useMutation } from '@apollo/client';

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
      }
    }
  }
`;

function AddTodo() {
  let input;
  const [addTodo, { data, loading, error }] = useMutation(ADD_TODO);

  if (loading) return 'Submitting...';
  if (error) return `Submission error! ${error.message}`;

  return (
    <div>
      <form
        onSubmit={e => {
          e.preventDefault();
          addTodo({ variables: { type: input.value } });
          input.value = '';
        }}
      >
        <input
          ref={node => {
            input = node;
          }}
        />
        <button type="submit">Add Todo</button>
      </form>
    </div>
  );
}

function CreateRequest1() {
  let input;
  const [createRequest, { data, loading, error }] = useMutation(ADD_REQUEST);

  if (loading) return 'Submitting...';
  if (error) return `Submission error! ${error.message}`;

  return (
    <div>
      <form
        onSubmit={e => {
          e.preventDefault();
          createRequest({ variables: { type: input.value } });
          input.value = '';
        }}
      >
        <input
          ref={node => {
            input = node;
          }}
        />
        <button type="submit">CreateRequest</button>
      </form>
    </div>
  );
}

// {
//   "input": {
//     "name": "Three monkeys",
//     "description": "Nice place",
//     "address": "25 Av. des Paulines, 63000 Clermont-Ferrand"
//   }
// }


function CreateRequest2() {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [address, setAddress] = useState('');
  //const [tags, setTags] = useState('');
  //const [email, setEmail] = useState('');

  const [createRequest, { data, loading, error }] = useMutation(ADD_REQUEST);

  if (loading) return 'Submitting...';
  if (error) return `Submission error! ${error.message}`;

  const handleSubmit = useCallback((event) => {
    event.preventDefault();

     // Get data from the form.
     const data = {
      name: name,
      description: description,
      address: address,
      //tags: tags,
      //email: email,
    }

    createRequest({ variables: { input: data } });

  }, [name, description, address]);

  const handleNameChange = useCallback((event) => {
    setName(event.target.value);
  }, []);
  const handleDescriptionChange = useCallback((event) => {
    setDescription(event.target.value);
  }, []);
  const handleAddressChange = useCallback((event) => {
    setAddress(event.target.value);
  }, []);
  // const handleTagsChange = useCallback((event) => {
  //   setTags(event.target.value);
  // }, []);
  // const handleEmailChange = useCallback((event) => {
  //   setEmail(event.target.value);
  // }, []);

  return (
    <form onSubmit={handleSubmit}>
      <label>
        Name:
        <input type="text" value={name} onChange={handleNameChange} />
      </label>
      <label>
        Description:
        <input type="text" value={description} onChange={handleDescriptionChange} />
      </label>
      <label>
        Address:
        <input type="text" value={address} onChange={handleAddressChange} />
      </label>
      {/* <label>
        Tags:
        <input type="text" value={email} onChange={handleTagsChange} />
      </label>
      <label>
        Email:
        <input type="email" value={email} onChange={handleEmailChange} />
      </label> */}
      <button type="submit">Submit</button>
    </form>
  );
}

export function CreateRequest() {

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
        console.log(data)
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

    setSubmissionError(null); // Reset the error state before making the mutation
    setSubmissionResult(null);

    createRequest({ variables: { input: form_data } });

    // if (loading) return 'Submitting...';
    // if (graphql_error) return `Submission error! ${error.message}`;
    if (submission_result) return `Returned data:  ${JSON.stringify(submission_result)}`;
  });


  return (
    <div>
       <h3>Add a Place</h3>
       {submission_result && (
        <div>
          Success! Place created with ID: {submission_result.id}, Name: {submission_result.name}, Address: {submission_result.address.address} ({submission_result.address.lat},{submission_result.address.long})
        </div>
      )}
      {submission_error ? <p>Oh no! {submission_error.message}</p> : null}
      {data && data.createRequest ? <p>Saved!</p> : null}
    
      <form onSubmit={handleSubmit}>
        <label>
          Name:
        <input type="text" name='name' /* ref={node => (this.inputNode = node)} *//> 
        </label>
        <label>
          Description:
          <input type="text" name='description' />
        </label>
        <label>
          Address:
          <input type="text" name='address' />
        </label>
      
        <button type="submit">Submit</button>
      </form>
    </div>
  );
}

export function PlaceForm() {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [address, setAddress] = useState('');
  //const [tags, setTags] = useState('');
  //const [email, setEmail] = useState('');

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault();

     // Get data from the form.
     const data = {
      name: name,
      description: description,
      address: address,
      //tags: tags,
      //email: email,
    }

    // Send the data to the server in JSON format.
    const JSONdata = JSON.stringify(data)

    console.log (JSONdata)
    
    // API endpoint where we send form data.
    const endpoint = '/api/place'

    // Form the request for sending data to the server.
    const options = {
      // The method is POST because we are sending data.
      method: 'POST',
      // Tell the server we're sending JSON.
      headers: {
        'Content-Type': 'application/json',
      },
      // Body of the request is the JSON data we created above.
      body: JSONdata,
    }

    // Send the form data to our forms API on Vercel and get a response.
    const response = await fetch(endpoint, options)

    // Get the response data from server as JSON.
    // If server returns the name submitted, that means the form works.
    const result = await response.json()
    alert(`Reply: ${result.data}`)

  }, [name, description, address]);

  const handleNameChange = useCallback((event) => {
    setName(event.target.value);
  }, []);
  const handleDescriptionChange = useCallback((event) => {
    setDescription(event.target.value);
  }, []);
  const handleAddressChange = useCallback((event) => {
    setAddress(event.target.value);
  }, []);
  // const handleTagsChange = useCallback((event) => {
  //   setTags(event.target.value);
  // }, []);
  // const handleEmailChange = useCallback((event) => {
  //   setEmail(event.target.value);
  // }, []);

  return (
    <form onSubmit={handleSubmit}>
      <label>
        Name:
        <input type="text" value={name} onChange={handleNameChange} />
      </label>
      <label>
        Description:
        <input type="text" value={description} onChange={handleDescriptionChange} />
      </label>
      <label>
        Address:
        <input type="text" value={address} onChange={handleAddressChange} />
      </label>
      {/* <label>
        Tags:
        <input type="text" value={email} onChange={handleTagsChange} />
      </label>
      <label>
        Email:
        <input type="email" value={email} onChange={handleEmailChange} />
      </label> */}
      <button type="submit">Submit</button>
    </form>
  );
}