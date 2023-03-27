import graphene

import products.schema, places.schema

class Query(products.schema.Query, places.schema.Query, graphene.ObjectType):
    # This class will inherit from multiple Queries
    # as we begin to add more apps to our project
    pass

schema = graphene.Schema(query=Query)