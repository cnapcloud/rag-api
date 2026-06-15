"""Dagster 리소스 — S3, IO manager."""

from __future__ import annotations

import pickle

from dagster import ConfigurableResource, IOManager


class S3Resource(ConfigurableResource):
    endpoint: str = "http://minio:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "rag-api"
    region: str = "us-east-1"
    insecure: bool = False

    def get_client(self):
        import boto3

        kwargs: dict = dict(
            service_name="s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )
        if self.insecure:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            kwargs["verify"] = False

        return boto3.client(**kwargs)


class S3PickleIOManager(IOManager):
    """Stores Dagster op outputs as pickled objects in MinIO/S3."""

    def __init__(self, s3_resource: S3Resource, bucket: str) -> None:
        self._s3 = s3_resource
        self._bucket = bucket

    def _key(self, context) -> str:
        return "/".join(context.get_identifier())

    def _ensure_bucket(self, client) -> None:
        from botocore.exceptions import ClientError

        try:
            client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchBucket", "404"):
                client.create_bucket(Bucket=self._bucket)
            else:
                raise

    def handle_output(self, context, obj) -> None:
        client = self._s3.get_client()
        self._ensure_bucket(client)
        client.put_object(Bucket=self._bucket, Key=self._key(context), Body=pickle.dumps(obj))

    def load_input(self, context):
        client = self._s3.get_client()
        response = client.get_object(Bucket=self._bucket, Key=self._key(context.upstream_output))
        return pickle.loads(response["Body"].read())


def build_resources_from_settings():
    """settings.yaml에서 Dagster 리소스를 빌드한다."""
    from config.settings import get_settings

    cfg = get_settings()
    s3_resource = S3Resource(
        endpoint=cfg.s3.endpoint,
        access_key=cfg.s3.access_key,
        secret_key=cfg.s3.secret_key,
        bucket=cfg.s3.rag_bucket,
        region=cfg.s3.region,
        insecure=cfg.s3.insecure,
    )
    return {
        "io_manager": S3PickleIOManager(s3_resource=s3_resource, bucket=cfg.s3.dagster_bucket),
    }
