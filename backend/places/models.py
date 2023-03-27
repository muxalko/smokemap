from django.db import models
from geopy.geocoders import Nominatim

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    
    class Meta:
        verbose_name_plural = 'Categories'
    def __str__(self):
        return self.name

class Tag(models.Model):
    name = models.CharField(max_length=100) 
    slug = models.SlugField(unique=True)
    # the tag belongs to a category
    category = models.ForeignKey(Category, blank=True, on_delete=models.PROTECT)

    class Meta:
        verbose_name_plural = 'Tags'
    def __str__(self):
        return self.name

# cache geocoding address resolve
class Address(models.Model):
    address = models.CharField(max_length=255)
    lat = models.FloatField(blank=True, null=True)
    long = models.FloatField(blank=True, null=True)

    def save(self, *args, **kwargs):
        geolocator = Nominatim(user_agent="smokemap")
        location = geolocator.geocode(self.address)
        self.lat = location.latitude
        self.long = location.longitude
        # g = geocoder.mapbox(self.address, key=mapbox_access_token)
        # g = g.latlng  # returns => [lat, long]
        # self.lat = g[0]
        # self.long = g[1]
        return super(Address, self).save(*args, **kwargs)
    
class Request(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    address = models.ForeignKey(Address, on_delete=models.PROTECT)
    imageurl = models.URLField(blank=True)
    date_created = models.DateField(auto_now_add=True)
    date_approved = models.DateField(blank=True, null=True)
    approved = models.BooleanField(default=False)
    # the item belongs to one category 
    # if having a category is required please remove blank=True
    # category = models.ForeignKey(Category, blank=True) 
    category = models.ForeignKey(Category, related_name='requests', on_delete=models.DO_NOTHING, blank=True, null=True)
    tags = models.ManyToManyField('Tag')

    class Meta:
        ordering = ['-date_created']

