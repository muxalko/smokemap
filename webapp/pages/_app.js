import '../styles/globals.css'
import { ApolloProvider } from "@apollo/client";
import { useApollo } from "../lib/apolloClient";
//import BooksList from "../components/booksLists";

function MyApp({Component, pageProps}) {
  const apolloClient = useApollo(pageProps.initialApolloState);

  return (
    <ApolloProvider client={apolloClient}>
        <Component {...pageProps} />
        
        {/* <BooksList /> */}
    </ApolloProvider>
  );
}

export default MyApp;
