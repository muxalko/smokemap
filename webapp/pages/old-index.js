import React, { useState, useEffect, useContext, useRef } from 'react';
import { CreateRequest } from '../components/form_place';
import ErrorBoundary from '../components/ErrorBoundary';
import PlacesList from '../components/placesLists';
import Map from '../components/map';
import styled from "styled-components";

const initialFlyTo = [52.51965492668956, 13.406841854355584]

export default function Index() {
  
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
            <ErrorBoundary>
              <h3>Add a new place</h3>
              <CreateRequest onSuccessfulCreation={setFlyTo} />
            </ErrorBoundary>
    
          <h4>Places</h4> 
          <PlacesList onClickHandler={setFlyTo}/>
 
        {/* Additional control elements */}
       

        </ControlContainer>
        <Clearfix />
    </>
    )
  }

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
