import * as React from 'react';

function ControlPanel(props) {
  const {year} = props;

  return (
    <div>
      <h3>Interactive GeoJSON</h3>
      <p>
        Map showing median household income by state in year <b>{year}</b>. Hover over a state to
        see details.
      </p>
      <p>
        Data source: <a href="www.census.gov">US Census Bureau</a>
      </p>
     
      <hr />

      <div key={'year'} >
        <label>Year</label>
        <input
          type="range"
          value={year}
          min={1995}
          max={2015}
          step={1}
          onChange={evt => props.onChange(evt.target.value)}
        />
      </div>
    </div>
  );
}

export default React.memo(ControlPanel);