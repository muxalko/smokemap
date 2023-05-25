import React, { useState, useEffect, useContext, useRef } from 'react';
import { ThemeContext } from './ThemeContext';
import { themes } from './ThemeContext';
import { PlaceForm, CreateRequest } from '../components/form_place';
import ErrorBoundary from '../components/ErrorBoundary';
import { ListCategory, AddCategory } from '../components/category'
import PlacesList from '../components/placesLists';
import RequestsList from '../components/requestsList';
import Map from '../components/map';
import styled from "styled-components";

const initialFlyTo = [52.51965492668956, 13.406841854355584]

export default function About() {

  const [refresh, setRefresh] = useState(false);
  
  const [flyTo, setFlyTo] = useState(initialFlyTo)

  useEffect(() => {
    console.log("Component render: About");
    console.log("About - flyTo: " + JSON.stringify(flyTo));
  });

  useEffect(() => {
    console.log("About - flyTo changed: " + JSON.stringify(flyTo));
  },[flyTo]);

    return ( 
      <>
        <Navbar>
          <Header>Smokemap v0.1</Header>
        </Navbar>
        <MapContainer>
          <Map flyTo={flyTo}/>
        </MapContainer>
        <ControlContainer>
            {/* Your form inputs using the TextInput and SelectInput components */}
            <ErrorBoundary>
              <h3>Add a new place</h3>
              <CreateRequest onSuccessfulCreation={setFlyTo} />
            </ErrorBoundary>
          <h4>Requests</h4>
          <RequestsList doRefresh={refresh} setRefresh={() => setRefresh()}/> 
          <h4>Places</h4> 
          <PlacesList onClickHandler={setFlyTo}/>
 
        {/* Additional control elements */}
       

        </ControlContainer>
        <Clearfix />
    </>
    )
  }

// const Container = styled.div`
//   height: 100vh;
//   width: 100%;
//   display: flex;
// `;
// const MapContainer = styled.div`
//   position: relative; 
//   top: 0; 
//   bottom: 0; 
//   width: 80%;
//   //z-index: -10;
// `
// const ControlsContainer = styled.div`
// position: relative;
// padding-left: 1em;
// top: 0; 
// bottom: 0; 
// width: 100%;
// //z-index: -10;
// `
// const Overlay = styled.div`
//   position: absolute;
//   top: 0;
//   left: 0;
//   width: 100%;
//   height: 100%;
//   background-color: rgba(0,0,0,0.5); /*dim the background*/
// `

const Navbar = styled.div`
  margin: 0;
  padding: 0px;
  background-color: black;
  color: white;
  text-align: center;
`;

const Header = styled.h1`
  padding: 20px;
  margin: 0;
`;

// Styled map container
const MapContainer = styled.div`
  width: 75%;
  height: 100vh;
  float: left;
`;

// Styled control elements container
const ControlContainer = styled.div`
  width: 25%;
  height: 100vh;
  float: left;
  box-sizing: border-box;
  padding: 20px;
`;

// Styled clearfix
const Clearfix = styled.div`
  &:after {
    content: "";
    display: table;
    clear: both;
  }
`;

// // example counter
// function Counter() {
//   const [count, setCount] = useState(0);

//   function handleClick() {
//     setCount(count + 1);
//   }

//   return (
//     <div>
//       <p>Count: {count}</p>
//       <button onClick={handleClick}>Increment</button>
//     </div>
//   );
// }

// // example data fetch from api route
// function DataFetcher() {
//   const [data, setData] = useState([]);

//   useEffect(() => {
//     async function fetchData() {
//       const response = await fetch('api/listNames');
//       const json = await response.json();
//       console.log(json)
//       setData(json);
//     }

//     fetchData();
//   }, []);

//   return (
//     <ul>
//       {data.map((item) => (
//         <li key={item.id}>{item.name}</li>
//       ))}
//     </ul>
//   );
// }

// // example theme switch
// function ThemedButton(props) {
//   const theme = useContext(ThemeContext);

//   return (
//     <button
//     // follow https://www.learnhowtoprogram.com/react/react-with-apis/help-queue-creating-a-context-and-provider
//       // style={{ background: theme.background, color: theme.foreground }}
//       style={{ background: 'blue', color: 'white' }}
//       {...props}
//     />
//   );
// }

// // example tesx input
// function TextInput() {
//   const inputRef = useRef(null);

//   function handleClick() {
//     inputRef.current.focus();
//   }

//   return (
//     <div>
//       <input type="text" ref={inputRef} />
//       <button onClick={handleClick}>Focus</button>
//     </div>
//   );
// }
