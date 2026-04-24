import boto3
import logging
from botocore.exceptions import ClientError
from app.config import settings

logger = logging.getLogger(__name__)

_s3 = None


def get_s3():
    global _s3
    if _s3 is None:
        if not settings.aws_access_key_id or not settings.aws_secret_access_key:
            return None
        _s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    return _s3


async def upload_media_to_s3(media_bytes: bytes, media_id: str, content_type: str = "application/octet-stream") -> str | None:
    """Upload WhatsApp media bytes to S3. Returns public URL or None if S3 not configured."""
    s3 = get_s3()
    if not s3:
        logger.debug("S3 not configured, skipping media upload")
        return None

    ext_map = {
        "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
        "video/mp4": "mp4", "audio/ogg": "ogg", "audio/mpeg": "mp3",
        "application/pdf": "pdf",
    }
    ext = ext_map.get(content_type, "bin")
    key = f"whatsapp-media/{media_id}.{ext}"

    try:
        s3.put_object(
            Bucket=settings.s3_bucket_name,
            Key=key,
            Body=media_bytes,
            ContentType=content_type,
        )
        url = f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{key}"
        logger.info(f"Uploaded media {media_id} to S3: {url}")
        return url
    except ClientError as e:
        logger.error(f"S3 upload failed for {media_id}: {e}")
        return None


def get_presigned_url(key: str, expires: int = 3600) -> str | None:
    """Generate a pre-signed URL for private S3 objects."""
    s3 = get_s3()
    if not s3:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": key},
            ExpiresIn=expires,
        )
    except ClientError as e:
        logger.error(f"Pre-signed URL generation failed: {e}")
        return None
