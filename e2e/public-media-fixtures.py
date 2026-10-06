import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.db import transaction

from backend.media_storage import configured_media_storage
from backend.models import (
    Address,
    CustomUser,
    Image,
    Location,
    MediaUploadIntent,
    Place,
    PublicMediaRendition,
    Request,
    SubmissionIdempotency,
    SubmissionLifecycleEvent,
)


OWNER_EMAIL = "user-one@smokemap.local"
APPROVED_NAME = "Smokemap E2E Issue 100 Approved Media Place"
REJECTED_NAME = "Smokemap E2E Issue 100 Rejected Media Place"
WITHDRAWN_NAME = "Smokemap E2E Issue 100 Withdrawn Media Place"
FIXTURE_NAMES = (APPROVED_NAME, REJECTED_NAME, WITHDRAWN_NAME)
SOURCE_MARKERS = {
    APPROVED_NAME: b"smokemap-e2e-approved-source-metadata",
    REJECTED_NAME: b"smokemap-e2e-rejected-source-metadata",
    WITHDRAWN_NAME: b"smokemap-e2e-withdrawn-source-metadata",
}
EXPECTED_LONGITUDE = -77.01215461524441
EXPECTED_LATITUDE = 38.89630256339336
STATE_DIR = os.environ.get("SMOKEMAP_E2E_STATE_DIR", "/workspace-e2e-state")
OBSERVATION_PATH = os.path.join(STATE_DIR, "public-observation.json")


class FixtureVerificationError(RuntimeError):
    pass


def _require(condition, message):
    if not condition:
        raise FixtureVerificationError(message)


def _owner():
    return CustomUser.objects.filter(email=OWNER_EMAIL).first()


def _submissions():
    owner = _owner()
    _require(owner is not None, f"fixture owner {OWNER_EMAIL} does not exist")
    rows = list(
        Request.objects.select_related("address", "owner")
        .filter(owner=owner, name__in=FIXTURE_NAMES)
        .order_by("pk")
    )
    by_name = {row.name: row for row in rows}
    _require(
        set(by_name) == set(FIXTURE_NAMES) and len(rows) == len(FIXTURE_NAMES),
        "expected exactly one named browser-created submission for each lifecycle",
    )
    return owner, by_name


def _read_object(storage, bucket, key):
    with storage.open_object(bucket=bucket, key=key) as body:
        return body.read()


def _anonymous_status(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _assert_storage_private(bucket, key, label):
    encoded_key = urllib.parse.quote(key, safe="/")
    status = _anonymous_status(f"http://storage:9000/{bucket}/{encoded_key}")
    _require(status in (403, 404), f"{label} was anonymously readable ({status})")


def _public_search(name):
    query = urllib.parse.urlencode({"q": name, "limit": 20})
    with urllib.request.urlopen(
        f"http://backend:8000/api/v1/places/search/?{query}", timeout=5
    ) as response:
        return json.load(response)["results"]


def _assert_not_public(name, label):
    results = _public_search(name)
    _require(
        all(item.get("name") != name for item in results),
        f"{label} unexpectedly appeared in anonymous public search",
    )


def _intent_and_image(submission):
    intents = list(MediaUploadIntent.objects.filter(submission=submission))
    images = list(Image.objects.filter(request=submission, is_managed=True))
    _require(len(intents) == 1, f"{submission.name}: expected one media intent")
    _require(len(images) == 1, f"{submission.name}: expected one managed image")
    _require(images[0].intent_id == intents[0].pk, f"{submission.name}: media mismatch")
    return intents[0], images[0]


def verify_pending():
    owner, submissions = _submissions()
    storage = configured_media_storage()
    for name, submission in submissions.items():
        _require(submission.state == Request.State.PENDING, f"{name}: not pending")
        _require(submission.owner_id == owner.pk, f"{name}: wrong owner")
        point = submission.address.location
        _require(
            abs(point.x - EXPECTED_LONGITUDE) < 1e-6
            and abs(point.y - EXPECTED_LATITUDE) < 1e-6,
            f"{name}: unexpected browser-selected point",
        )
        intent, image = _intent_and_image(submission)
        _require(intent.state == MediaUploadIntent.State.ATTACHED, f"{name}: intent not attached")
        _require(image.state == "attached", f"{name}: image not attached")
        source = _read_object(storage, image.storage_bucket, image.storage_key)
        rendition = _read_object(
            storage, intent.storage_bucket, intent.rendition_object_key
        )
        _require(SOURCE_MARKERS[name] in source, f"{name}: source marker missing")
        _require(SOURCE_MARKERS[name] not in rendition, f"{name}: rendition retained metadata")
        _require(
            hashlib.sha256(rendition).hexdigest() == intent.rendition_sha256,
            f"{name}: rendition digest mismatch",
        )
        _assert_storage_private(image.storage_bucket, image.storage_key, f"{name} source")
        _assert_storage_private(
            intent.storage_bucket, intent.rendition_object_key, f"{name} rendition"
        )
        _require(
            not PublicMediaRendition.objects.filter(intent=intent).exists(),
            f"{name}: pending media already has a public binding",
        )
        _assert_not_public(name, name)
    print("Pending media privacy checkpoint passed for all three browser submissions.")


def _load_observation():
    try:
        with open(OBSERVATION_PATH, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as error:
        raise FixtureVerificationError("anonymous browser observation is unavailable") from error


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def verify_final():
    owner, submissions = _submissions()
    approved = submissions[APPROVED_NAME]
    rejected = submissions[REJECTED_NAME]
    withdrawn = submissions[WITHDRAWN_NAME]
    _require(approved.state == Request.State.APPROVED, "approved fixture is not approved")
    _require(rejected.state == Request.State.REJECTED, "rejected fixture is not rejected")
    _require(withdrawn.state == Request.State.WITHDRAWN, "withdrawn fixture is not withdrawn")

    approval = SubmissionIdempotency.objects.get(
        submission=approved, operation="submission.approve.v4"
    )
    place = Place.objects.get(pk=approval.original_result["place_id"])
    _require(place.name == APPROVED_NAME, "approval materialized the wrong Place")
    intent, image = _intent_and_image(approved)
    rendition = PublicMediaRendition.objects.get(intent=intent)
    _require(rendition.place_id == place.pk, "public rendition points at the wrong Place")
    _require(rendition.state == PublicMediaRendition.State.PUBLISHED, "rendition not published")

    storage = configured_media_storage()
    source = _read_object(storage, image.storage_bucket, image.storage_key)
    private_rendition = _read_object(
        storage, intent.storage_bucket, intent.rendition_object_key
    )
    _require(SOURCE_MARKERS[APPROVED_NAME] in source, "approved source marker missing")
    _require(
        SOURCE_MARKERS[APPROVED_NAME] not in private_rendition,
        "approved display rendition retained source metadata",
    )
    _assert_storage_private(image.storage_bucket, image.storage_key, "approved source")
    _assert_storage_private(
        intent.storage_bucket, intent.rendition_object_key, "approved rendition object"
    )
    public_url = f"http://backend:8000/api/v1/media/{rendition.public_id}/"
    with urllib.request.urlopen(public_url, timeout=5) as response:
        public_body = response.read()
        _require(response.status == 200, "application media endpoint did not return 200")
        _require(response.headers.get("Cache-Control") == "no-store", "public media was cacheable")
        _require(response.headers.get("X-Content-Type-Options") == "nosniff", "nosniff missing")
    _require(public_body == private_rendition, "public endpoint did not serve the approved rendition")
    _require(public_body != source, "public endpoint served the private source bytes")

    for label, submission in (("rejected", rejected), ("withdrawn", withdrawn)):
        intents = list(MediaUploadIntent.objects.filter(submission=submission))
        _require(len(intents) == 1, f"{label}: expected retained cleanup evidence")
        cleanup_intent = intents[0]
        _require(
            cleanup_intent.state in {
                MediaUploadIntent.State.CLEANUP_PENDING,
                MediaUploadIntent.State.DELETED,
            },
            f"{label}: media did not enter cleanup",
        )
        _require(
            not Image.objects.filter(request=submission, is_managed=True).exists(),
            f"{label}: managed image remained attached",
        )
        _require(
            not PublicMediaRendition.objects.filter(intent=cleanup_intent).exists(),
            f"{label}: public rendition was created",
        )
        for key in (
            cleanup_intent.object_key,
            cleanup_intent.sealed_object_key,
            cleanup_intent.rendition_object_key,
        ):
            _assert_storage_private(cleanup_intent.storage_bucket, key, f"{label} media")
        _assert_not_public(submission.name, label)

    observation = _load_observation()
    _require(observation.get("approvedName") == APPROVED_NAME, "approved UI evidence missing")
    _require(observation.get("imageRendered") is True, "approved rendition did not render")
    _require(
        observation.get("authenticatedCookieNames") == [],
        "public proof used an authenticated browser session",
    )
    encoded = json.dumps(observation, sort_keys=True)
    forbidden_strings = {
        OWNER_EMAIL,
        owner.name,
        settings.MEDIA_STORAGE_BUCKET_NAME,
        "submission-media-uploads/",
        "submission-media-sealed/",
        "submission-media-renditions/",
    }
    for fixture in submissions.values():
        for media_intent in MediaUploadIntent.objects.filter(submission=fixture):
            forbidden_strings.update(
                {
                    str(media_intent.pk),
                    media_intent.object_key,
                    media_intent.sealed_object_key,
                    media_intent.rendition_object_key,
                }
            )
    for value in forbidden_strings:
        _require(value not in encoded, "anonymous evidence exposed private identity/storage metadata")
    forbidden_keys = {
        "owner",
        "ownerId",
        "request",
        "requestId",
        "submission",
        "submissionId",
        "mediaIntent",
        "mediaIntentId",
        "moderationAudit",
        "auditId",
        "storageBucket",
        "storageKey",
        "objectKey",
    }
    _require(
        forbidden_keys.isdisjoint(set(_walk_keys(observation.get("publicPayloads", [])))),
        "anonymous public payload contained a prohibited metadata field",
    )
    print("Approved public rendition and rejected/withdrawn non-public lifecycle verified.")


def cleanup():
    owner = _owner()
    if owner is None:
        if os.path.exists(OBSERVATION_PATH):
            os.remove(OBSERVATION_PATH)
        print("Public media E2E fixture owner is absent; state file cleaned.")
        return
    submissions = list(Request.objects.filter(owner=owner, name__in=FIXTURE_NAMES))
    submission_ids = [submission.pk for submission in submissions]
    address_ids = [submission.address_id for submission in submissions]
    intents = list(MediaUploadIntent.objects.filter(submission_id__in=submission_ids))
    storage = configured_media_storage()
    for intent in intents:
        for key in (intent.object_key, intent.sealed_object_key, intent.rendition_object_key):
            storage.delete_object(bucket=intent.storage_bucket, key=key)

    approval_place_ids = {
        row.original_result.get("place_id")
        for row in SubmissionIdempotency.objects.filter(
            submission_id__in=submission_ids, operation="submission.approve.v4"
        )
        if row.original_result.get("place_id") is not None
    }
    PublicMediaRendition.objects.filter(intent__in=intents).delete()
    Image.objects.filter(request_id__in=submission_ids).delete()
    Location.objects.filter(place_id__in=[str(value) for value in approval_place_ids]).delete()
    Place.objects.filter(pk__in=approval_place_ids).delete()
    events = SubmissionLifecycleEvent.objects.filter(submission_id__in=submission_ids)
    events._raw_delete(using=events.db)
    SubmissionIdempotency.objects.filter(submission_id__in=submission_ids).delete()
    MediaUploadIntent.objects.filter(submission_id__in=submission_ids).delete()
    Request.objects.filter(pk__in=submission_ids).delete()
    Address.objects.filter(pk__in=address_ids).delete()
    if os.path.exists(OBSERVATION_PATH):
        os.remove(OBSERVATION_PATH)
    print(f"Cleaned {len(submissions)} public media E2E submission aggregate(s).")


if not settings.DEBUG:
    raise RuntimeError("Public media E2E fixtures require Django DEBUG mode")

action = os.environ.get("SMOKEMAP_E2E_FIXTURE_ACTION")
if action == "cleanup":
    with transaction.atomic():
        cleanup()
elif action == "verify_pending":
    verify_pending()
elif action == "verify_final":
    verify_final()
else:
    raise RuntimeError(
        "SMOKEMAP_E2E_FIXTURE_ACTION must be cleanup, verify_pending or verify_final"
    )
