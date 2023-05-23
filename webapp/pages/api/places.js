import { gql, useQuery, useLazyQuery } from "@apollo/client";
import { ALL_PLACES_QUERY } from "../../src/graphql/queries/place";

export default (req, res) => {

  //const [getPlaces, { called, data, loading, error }] = useLazyQuery(ALL_PLACES_QUERY);
  // const { data: pointsData, isLoading } = useQuery(pointsLayerId, () => {
  //   const [
  //       getPlaces,
  //       { called, data, loading, error }
  //     ] = useQuery(ALL_PLACES_QUERY, {
  //       variables: {
  //         name: 'The Pub',
  //       },
  //       fetchPolicy: 'network-only',
  //       onCompleted: (d) => {
  //         console.log("onCompleted: " + d)
  //         res.statusCode = 200;
  //         res.json({
  //           test: 1
  //         });
  //       }
  //     });
  // },
  // );

  const { data: { points } = {}, loading } = useQuery(
    gql`
      query GetPoints {
          requests {
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
    `,
    {
      fetchPolicy: 'cache-and-network',
    }
  );

  res.statusCode = 200;
  res.json(data);
};
