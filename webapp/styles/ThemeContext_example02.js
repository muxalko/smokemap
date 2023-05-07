import React from 'react';

const ThemeContext = React.createContext(
  'theme-light'
);

export function ThemeProvider({ children }) {
  const [theme, setTheme] = React.useState(
    'theme-dark'
  );

  function toggleTheme() {
    setTheme((currentTheme) =>
      currentTheme === 'theme-light'
        ? 'theme-dark'
        : 'theme-light'
    );
  }

  return (
    <ThemeContext.Provider
      value={{ theme, toggleTheme }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = React.useContext(ThemeContext)

  if (!context) {
    throw new Error(`"useTheme" must be called inside a "ThemeProvider"`)
  }

  return context
}
