import React, { useState, useEffect, useContext, useRef } from 'react';
import { ThemeContext } from './ThemeContext';
import { themes } from './ThemeContext';
import { PlaceForm, CreateRequest } from '../components/form_place';
import ErrorBoundary from '../components/ErrorBoundary';
import { ListCategory, AddCategory } from '../components/category'
function Counter() {
  const [count, setCount] = useState(0);

  function handleClick() {
    setCount(count + 1);
  }

  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={handleClick}>Increment</button>
    </div>
  );
}

function DataFetcher() {
  const [data, setData] = useState([]);

  useEffect(() => {
    async function fetchData() {
      const response = await fetch('api/listNames');
      const json = await response.json();
      console.log(json)
      setData(json);
    }

    fetchData();
  }, []);

  return (
    <ul>
      {data.map((item) => (
        <li key={item.id}>{item.name}</li>
      ))}
    </ul>
  );
}

function ThemedButton(props) {
  const theme = useContext(ThemeContext);

  return (
    <button
    // follow https://www.learnhowtoprogram.com/react/react-with-apis/help-queue-creating-a-context-and-provider
      // style={{ background: theme.background, color: theme.foreground }}
      style={{ background: 'blue', color: 'white' }}
      {...props}
    />
  );
}

function TextInput() {
  const inputRef = useRef(null);

  function handleClick() {
    inputRef.current.focus();
  }

  return (
    <div>
      <input type="text" ref={inputRef} />
      <button onClick={handleClick}>Focus</button>
    </div>
  );
}

export default function About() {
    return ( 
    <div>
      <ErrorBoundary>
        <CreateRequest />
      </ErrorBoundary>
    </div>
    )
  }