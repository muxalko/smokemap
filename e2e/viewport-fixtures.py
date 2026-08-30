import os

from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction

from backend.models import Address, Category, Place


FIXTURES = (
    {
        "name": "Smokemap E2E Issue 52 Region A",
        "address": "Smokemap E2E Issue 52 Region A fixture",
        "longitude": -77.01215461524441,
        "latitude": 38.89630256339336,
    },
    {
        "name": "Smokemap E2E Issue 52 Region B",
        "address": "Smokemap E2E Issue 52 Region B fixture",
        "longitude": -76.86715461524441,
        "latitude": 38.89630256339336,
    },
)


def cleanup():
    names = [fixture["name"] for fixture in FIXTURES]
    addresses = [fixture["address"] for fixture in FIXTURES]
    Place.objects.filter(name__in=names).delete()
    Address.objects.filter(addressString__in=addresses).delete()


def seed():
    category = Category.objects.get(name="Outdoors")
    cleanup()
    for fixture in FIXTURES:
        point = Point(
            fixture["longitude"],
            fixture["latitude"],
            srid=4326,
        )
        address = Address(
            addressString=fixture["address"],
            location=point,
        )
        address.save(omit_geocode=True)
        Place.objects.create(
            name=fixture["name"],
            category=category,
            description=f"Deterministic {fixture['name']} browser fixture.",
            address=address,
            website=None,
        )


if not settings.DEBUG:
    raise RuntimeError("Viewport browser fixtures require Django DEBUG mode")

action = os.environ.get("SMOKEMAP_E2E_FIXTURE_ACTION")
if action not in {"seed", "cleanup"}:
    raise RuntimeError("SMOKEMAP_E2E_FIXTURE_ACTION must be seed or cleanup")

with transaction.atomic():
    seed() if action == "seed" else cleanup()

print(f"Viewport browser fixtures {action} complete.")
