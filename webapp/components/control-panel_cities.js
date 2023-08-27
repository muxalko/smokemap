import * as React from 'react';

import CITIES from './.data/cities.json';

import styled from "styled-components";

function ControlPanel(props) {
  return (
    <ControlPanelContainer>
      <h3>Camera Transition</h3>
      <p>Smooth animate of the viewport.</p>
      <div className="source-link">
        <a
          href="https://github.com/visgl/react-map-gl/tree/7.1-release/examples/viewport-animation"
          target="_new"
        >
          View Code ↗
        </a>
      </div>
      <hr />

      {CITIES.filter(city => city.state === 'Washington').map((city, index) => (
        <div key={`btn-${index}`} className="input">
          <input
            type="radio"
            name="city"
            id={`city-${index}`}
            defaultChecked={city.city === 'Seattle'}
            onClick={() => props.onSelectCity(city)}
          />
          <label htmlFor={`city-${index}`}>{city.city}</label>
        </div>
      ))}
    </ControlPanelContainer>
  );
}

export default React.memo(ControlPanel);

const ControlPanelContainer = styled.div`
    position: absolute;
    top: 0;
    right: 0;
    max-width: 320px;
    background: #fff;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
    padding: 12px 24px;
    margin: 20px;
    font-size: 13px;
    line-height: 2;
    color: #6b6b76;
    text-transform: uppercase;
    outline: none;
`