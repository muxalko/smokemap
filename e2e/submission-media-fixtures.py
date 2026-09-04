import os
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction

from backend.media_storage import configured_media_storage
from backend.models import (
    Address,
    CustomUser,
    Image,
    MediaUploadIntent,
    Request,
    SubmissionIdempotency,
    SubmissionLifecycleEvent,
)


# Kept in lockstep with the equivalent constants in e2e/submission-media.mjs;
# each file is self-contained on purpose, matching e2e/viewport-fixtures.py
# and e2e/viewport-pan.mjs.
OWNER_EMAIL = "user-one@smokemap.local"
ZERO_IMAGE_NAME = "Smokemap E2E Issue 77 Zero Image Place"
MULTI_IMAGE_NAME = "Smokemap E2E Issue 77 Multi Image Place"
FIXTURE_NAMES = (ZERO_IMAGE_NAME, MULTI_IMAGE_NAME)
MULTI_IMAGE_COUNT = 2
EXPECTED_LONGITUDE = -77.01215461524441
EXPECTED_LATITUDE = 38.89630256339336
COORDINATE_TOLERANCE = 1e-6
ALLOWED_MEDIA_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

ZERO_IMAGE_OPERATIONS = ["submission.create.v3", "submission.finalize.v3"]
MULTI_IMAGE_OPERATIONS = list(ZERO_IMAGE_OPERATIONS)
for _ in range(MULTI_IMAGE_COUNT):
    MULTI_IMAGE_OPERATIONS += [
        "media.intent.create.v3",
        "media.intent.issue.v3",
        "media.intent.verify.v3",
        "media.intent.attach.v3",
    ]


class FixtureVerificationError(RuntimeError):
    pass


def _require(condition, message):
    if not condition:
        raise FixtureVerificationError(message)


def _owner():
    return CustomUser.objects.filter(email=OWNER_EMAIL).first()


def cleanup():
    owner = _owner()
    if owner is None:
        print("Submission media E2E fixture owner is absent; nothing to clean up.")
        return
    submission_ids = list(
        Request.objects.filter(owner=owner, name__in=FIXTURE_NAMES).values_list(
            "pk", flat=True
        )
    )
    if not submission_ids:
        print("No submission media E2E fixture rows present.")
        return
    address_ids = list(
        Request.objects.filter(pk__in=submission_ids).values_list(
            "address_id", flat=True
        )
    )

    # The Django rows below are only metadata. Deleting them alone leaves the
    # real sealed (and, for any run that failed before backend verification's
    # own post-verify cleanup, original) objects behind in the private MinIO
    # bucket forever, since nothing else ever revisits a hard-deleted row.
    # Delete the real objects first so a rerun never accumulates storage
    # bytes; S3-style DELETE is idempotent, so a key that is already absent
    # (the common case for the original upload object) is not an error.
    storage = configured_media_storage()
    images = list(Image.objects.filter(request_id__in=submission_ids, is_managed=True))
    intents = list(MediaUploadIntent.objects.filter(submission_id__in=submission_ids))
    for image in images:
        storage.delete_object(bucket=image.storage_bucket, key=image.storage_key)
    for intent in intents:
        storage.delete_object(bucket=intent.storage_bucket, key=intent.object_key)
        storage.delete_object(bucket=intent.storage_bucket, key=intent.sealed_object_key)

    # Deletion order matters: Image.intent and SubmissionIdempotency.media_intent
    # both PROTECT MediaUploadIntent, and Request.address PROTECTs Address.
    Image.objects.filter(request_id__in=submission_ids, is_managed=True).delete()
    SubmissionIdempotency.objects.filter(submission_id__in=submission_ids).delete()
    MediaUploadIntent.objects.filter(submission_id__in=submission_ids).delete()
    SubmissionLifecycleEvent.objects.filter(submission_id__in=submission_ids).delete()
    Request.objects.filter(pk__in=submission_ids).delete()
    Address.objects.filter(pk__in=address_ids).delete()
    print(
        f"Cleaned up {len(submission_ids)} submission media E2E fixture submission(s) "
        f"and {len(images) + len(intents) * 2} associated storage object(s)."
    )


def _verify_point(submission, label):
    point = submission.address.location
    _require(
        abs(point[0] - EXPECTED_LONGITUDE) < COORDINATE_TOLERANCE
        and abs(point[1] - EXPECTED_LATITUDE) < COORDINATE_TOLERANCE,
        f"{label}: unexpected submitted point {point.coords}",
    )


def _verify_common(submission, owner, label):
    _require(submission.owner_id == owner.pk, f"{label}: unexpected owner")
    _require(
        submission.state == "pending",
        f"{label}: expected pending state, found {submission.state}",
    )
    _verify_point(submission, label)


def _verify_idempotency_rows(submission, label, expected_operations):
    rows = list(SubmissionIdempotency.objects.filter(submission=submission))
    _require(
        len(rows) == len(expected_operations),
        f"{label}: expected {len(expected_operations)} idempotency row(s), found {len(rows)}",
    )
    _require(
        sorted(row.operation for row in rows) == sorted(expected_operations),
        f"{label}: unexpected idempotency operations {sorted(row.operation for row in rows)}",
    )


def _verify_intents(submission, label, *, expected_count):
    intents = list(MediaUploadIntent.objects.filter(submission=submission))
    _require(
        len(intents) == expected_count,
        f"{label}: expected {expected_count} media intent(s), found {len(intents)}",
    )
    return intents


def _verify_object_is_private(bucket, key, label):
    url = f"http://storage:9000/{bucket}/{key}"
    try:
        urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as error:
        _require(
            error.code in (403, 404),
            f"{label}: anonymous read of {url} returned unexpected status {error.code}",
        )
        return
    except urllib.error.URLError as error:
        raise FixtureVerificationError(
            f"{label}: could not reach the private storage endpoint at {url}: {error}"
        ) from error
    raise FixtureVerificationError(f"{label}: object is anonymously readable at {url}")


def _verify_zero_image(submission, owner):
    label = "zero-image submission"
    _verify_common(submission, owner, label)
    attachment_count = Image.objects.filter(request=submission, is_managed=True).count()
    _require(
        attachment_count == 0,
        f"{label}: expected zero attachments, found {attachment_count}",
    )
    _verify_intents(submission, label, expected_count=0)
    _verify_idempotency_rows(submission, label, ZERO_IMAGE_OPERATIONS)


def _verify_multi_image(submission, owner):
    label = "multi-image submission"
    _verify_common(submission, owner, label)

    attachments = list(
        Image.objects.filter(request=submission, is_managed=True, state="attached").order_by(
            "position"
        )
    )
    _require(
        len(attachments) == MULTI_IMAGE_COUNT,
        f"{label}: expected {MULTI_IMAGE_COUNT} attached image(s), found {len(attachments)}",
    )
    _require(
        [attachment.position for attachment in attachments] == list(range(MULTI_IMAGE_COUNT)),
        f"{label}: attachment positions are not the contiguous ordering 0..{MULTI_IMAGE_COUNT - 1}",
    )

    storage = configured_media_storage()
    bucket = settings.MEDIA_STORAGE_BUCKET_NAME
    digests = set()
    for attachment in attachments:
        _require(
            attachment.owner_id == owner.pk, f"{label}: attachment owner mismatch"
        )
        _require(
            attachment.detected_mime in ALLOWED_MEDIA_MIME_TYPES,
            f"{label}: unexpected detected mime {attachment.detected_mime}",
        )
        _require(
            0 < attachment.byte_size <= 5_000_000,
            f"{label}: unexpected byte size {attachment.byte_size}",
        )
        _require(
            bool(attachment.width) and bool(attachment.height),
            f"{label}: missing verified dimensions",
        )
        _require(
            attachment.storage_bucket == bucket,
            f"{label}: attachment stored in unexpected bucket {attachment.storage_bucket}",
        )
        _require(
            attachment.storage_key.startswith(f"submission-media-sealed/{submission.pk}/"),
            f"{label}: unexpected sealed storage key {attachment.storage_key}",
        )
        digests.add(attachment.sha256)

        size = storage.object_size(bucket=attachment.storage_bucket, key=attachment.storage_key)
        _require(
            size == attachment.byte_size,
            f"{label}: sealed object size {size} does not match recorded byte size {attachment.byte_size}",
        )
        _verify_object_is_private(attachment.storage_bucket, attachment.storage_key, label)

    _require(
        len(digests) == MULTI_IMAGE_COUNT,
        f"{label}: attached images do not have distinct server-verified digests",
    )

    intents = _verify_intents(submission, label, expected_count=MULTI_IMAGE_COUNT)
    for intent in intents:
        _require(
            intent.state == "attached",
            f"{label}: media intent {intent.pk} left in non-terminal state {intent.state}",
        )
        _require(
            storage.object_is_absent(bucket=intent.storage_bucket, key=intent.object_key),
            f"{label}: unsealed upload object was not cleaned up after verification: {intent.object_key}",
        )

    _verify_idempotency_rows(submission, label, MULTI_IMAGE_OPERATIONS)


def verify():
    owner = _owner()
    _require(owner is not None, f"fixture owner {OWNER_EMAIL} does not exist")

    zero = (
        Request.objects.select_related("address")
        .filter(name=ZERO_IMAGE_NAME)
        .order_by("-date_created")
        .first()
    )
    _require(zero is not None, f"zero-image fixture submission not found: {ZERO_IMAGE_NAME}")
    _verify_zero_image(zero, owner)

    multi = (
        Request.objects.select_related("address")
        .filter(name=MULTI_IMAGE_NAME)
        .order_by("-date_created")
        .first()
    )
    _require(multi is not None, f"multi-image fixture submission not found: {MULTI_IMAGE_NAME}")
    _require(multi.pk != zero.pk, "zero-image and multi-image fixtures resolved to the same row")
    _verify_multi_image(multi, owner)

    print(
        "Submission and media E2E backend, privacy and cleanup verification passed "
        f"for submissions {zero.pk} (zero-image) and {multi.pk} (multi-image)."
    )


if not settings.DEBUG:
    raise RuntimeError("Submission media E2E fixtures require Django DEBUG mode")

action = os.environ.get("SMOKEMAP_E2E_FIXTURE_ACTION")
if action not in {"cleanup", "verify"}:
    raise RuntimeError("SMOKEMAP_E2E_FIXTURE_ACTION must be cleanup or verify")

if action == "cleanup":
    with transaction.atomic():
        cleanup()
else:
    verify()
