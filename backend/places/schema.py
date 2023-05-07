import graphene
from graphene_django import DjangoObjectType
from .models import Category, Tag, Request, Address
from django.core.exceptions import ValidationError

class CategoryType(DjangoObjectType):
    class Meta: 
        model = Category
        fields = ('id','name')

class TagType(DjangoObjectType):
    class Meta: 
        model = Tag
        fields = ('id','name', 'category')

class AddressType(DjangoObjectType):
    class Meta: 
        model = Address
        fields = (
            'id',
            'address',
            'lat',
            'long'
        )  

class RequestType(DjangoObjectType):
    class Meta: 
        model = Request
        fields = (
            'id',
            'name',
            'description',
            'address'
            # 'imageurl',
            # 'date_created', 
            # 'date_approved',
            # 'approved', 
            # 'category',
           # 'tags'
        )  

class Query(graphene.ObjectType):
    categories = graphene.List(CategoryType)
    #tags = graphene.List(TagType)
    #addresses = graphene.List(AddressType)
    requests = graphene.List(RequestType)

    def resolve_categories(root, info, **kwargs):
        # Querying a list
        return Category.objects.all()

    # def resolve_tags(root, info, **kwargs):
    #     # Querying a list
    #     return Tag.objects.all()
    
    def resolve_addresses(root, info, **kwargs):
        # Querying a list
        return Address.objects.all()
        
    def resolve_requests(root, info, **kwargs):
        # Querying a list
        return Request.objects.all()


class UpdateCategory(graphene.Mutation):
    class Arguments:
        # Mutation to update a category 
        name = graphene.String(required=True)
        id = graphene.ID()


    category = graphene.Field(CategoryType)

    @classmethod
    def mutate(cls, root, info, name, id):
        category = Category.objects.get(pk=id)
        category.name = name
        category.save()
        
        return UpdateCategory(category=category)

class CreateCategory(graphene.Mutation):
    class Arguments:
        # Mutation to create a category
        name = graphene.String(required=True)

    # Class attributes define the response of the mutation
    category = graphene.Field(CategoryType)

    @classmethod
    def mutate(cls, root, info, name):
        category = Category()
        category.name = name
        category.save()
        
        return CreateCategory(category=category)

class RequestInput(graphene.InputObjectType):
    name = graphene.String()
    description = graphene.String()
    address_string = graphene.String()
    #imageurl = graphene.String()
    #date_created = graphene.DateTime() #YYYY-MM-DDTHH:mm:ss.sssZ
    #date_approved = graphene.DateTime()
    #approved = graphene.Boolean
    #category = graphene.String()
    #tags = graphene.String()

class CreateRequest(graphene.Mutation):
    class Arguments:
        input = RequestInput(required=True)

    request = graphene.Field(RequestType)
    
    @classmethod
    def mutate(cls, root, info, input):

        myaddress = Address()
        myaddress.address = input.address_string
        myaddress.save()

        # category = Category(CategoryType)
        # category.name = input.category
        # tag = Tag.objects.get(id=1) 

        request = Request()
        request.name = input.name
        request.description = input.description
        request.address = myaddress
        #request.imageurl = input.imageurl
        #request.date_created = input.date_created
        #request.date_approved = input.date_approved
        #request.approved = input.approved
        #request.category = category
        #request.tags = [tag, tag, tag]
        #request.tags.add(tag)
        request.save()
        return CreateRequest(request=request)

class UpdateRequest(graphene.Mutation):
    class Arguments:
        input = RequestInput(required=True)
        id = graphene.ID()

    request = graphene.Field(RequestType)
    
    @classmethod
    def mutate(cls, root, info, input, id):
        request = Request.objects.get(pk=id)
        request.name = input.name
        request.description = input.description
        request.address = input.address
        # request.imageurl = input.imageurl
        # request.date_created = input.date_created
        # request.date_approved = input.date_approved
        # request.approved = input.approved
        # request.category = input.category
        #request.tags = input.tags

        request.save()
        return UpdateRequest(request=request)

class Mutation(graphene.ObjectType):
    update_category = UpdateCategory.Field()
    create_category = CreateCategory.Field()
    create_request = CreateRequest.Field()
    update_request = UpdateRequest.Field()

schema = graphene.Schema(query=Query, mutation=Mutation)