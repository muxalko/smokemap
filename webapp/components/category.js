import { gql, useQuery, useMutation } from '@apollo/client';

const ADD_CATEGORY = gql`
  mutation CreateCategory($name: String!) {
    createCategory(name: $name) {
      category {
        id
        name
      }
    }
  }
`;

const LIST_CATEGORY = gql`
  query {
  categories {
    id
    name
  }
}
`;

export function AddCategory() {
    let input;
    const [addCategory, { data, loading, error }] = useMutation(ADD_CATEGORY);
  
    if (loading) return 'Submitting...';
    if (error) return `Submission error! ${error.message}`;
  
    return (
      <div>
        <form
          onSubmit={e => {
            e.preventDefault();
            addCategory({ variables: { name: input.value } });
            input.value = '';
          }}
        >
          <input
            ref={node => {
              input = node;
            }}
          />
          <button type="submit">Add Category</button>
        </form>
      </div>
    );
  }

  
export function ListCategory() {
  const { loading, error, data } = useQuery(LIST_CATEGORY);

  if (error) return <div>Error loading Categories.</div>;
  if (loading) return <div>Loading</div>;

  const { categories } = data;

  console.log("categories", categories)

  var categorieslist = categories.map(function(category){
    return <li key={category.id}>{category.name}</li>
  })


  return <ul>{categorieslist}</ul>;
}