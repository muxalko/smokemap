from django.contrib import admin
from .models import Category, Tag, Address, Request
# Register your models here.
admin.site.register(Category)
admin.site.register(Tag)
admin.site.register(Address)
admin.site.register(Request)

