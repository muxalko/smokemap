import '../styles/globals.css'
import { ApolloProvider } from "@apollo/client";
import { useApollo } from "../lib/apolloClient";

//import App from 'next/app';

function MyApp({Component, pageProps}) {
  const apolloClient = useApollo(pageProps.initialApolloState);

  return (
     <ApolloProvider client={apolloClient}>
        <Component {...pageProps} />
        
    </ApolloProvider>
  );
};

// MyApp.getInitialProps = async (appContext) => {
//   // calls page's `getInitialProps` and fills `appProps.pageProps`
//   const appProps = await App.getInitialProps(appContext);

//   return { ...appProps };
// };

// MyApp.getInitialProps = async (appContext) => {
//   let pageProps = {};
//   if (appContext.Component.getInitialProps) {
//       pageProps = await appContext.Component.getInitialProps(appContext.ctx);
//   }
//   return { ...pageProps }
// };

export default MyApp;
