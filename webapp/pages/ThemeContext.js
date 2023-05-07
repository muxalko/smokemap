
import React from 'react';

export const themes = {
    light: {
      backgroundColor: "AntiqueWhite",
      textColor: "DarkSlateGrey",
      buttonBackground: "Lavender", 
      inputBackground: "Gainsboro"
    },
    dark: {
      backgroundColor: "DarkSlateGrey",
      textColor: "AntiqueWhite",
      buttonBackground: "#232b3c",
      inputBackground: "#45516d"
    }
  };

export const ThemeContext = React.createContext();