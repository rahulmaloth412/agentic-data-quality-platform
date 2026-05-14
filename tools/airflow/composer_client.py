"""Cloud Composer / Airflow REST API client for DAG management."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import aiohttp
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from configs.settings import get_settings

logger = structlog.get_logger(__name__)


class AirflowClient:
    """Async Airflow REST API client for Cloud Composer interactions."""

    def __init__(
        self,
        webserver_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (webserver_url or settings.airflow.webserver_url).rstrip("/")
        self._username = username or settings.airflow.username
        self._password = password or settings.airflow.password
        self._api_url = f"{self._base_url}/api/v1"
        self._log = logger.bind(base_url=self._base_url)

    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(login=self._username, password=self._password)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30), reraise=True)
    async def trigger_dag(self, dag_id: str, conf: Optional[dict[str, Any]] = None) -> str:
        """Trigger a DAG run and return the run_id."""
        url = f"{self._api_url}/dags/{dag_id}/dagRuns"
        payload: dict[str, Any] = {"conf": conf or {}}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, auth=self._auth()) as resp:
                resp.raise_for_status()
                data = await resp.json()
                run_id = data.get("dag_run_id", "")
                self._log.info("dag_triggered", dag_id=dag_id, run_id=run_id)
                return run_id

    async def get_dag_run_status(self, dag_id: str, run_id: str) -> str:
        """Return the state of a specific DAG run."""
        url = f"{self._api_url}/dags/{dag_id}/dagRuns/{run_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=self._auth()) as resp:
                if resp.status == 404:
                    return "not_found"
                resp.raise_for_status()
                data = await resp.json()
                return data.get("state", "unknown")

    async def upload_dag_file(
        self, dag_content: str, dag_filename: str, gcs_bucket: Optional[str] = None
    ) -> None:
        """Upload a DAG file to the GCS bucket backing Cloud Composer."""
        settings = get_settings()
        bucket = gcs_bucket or settings.airflow.dag_bucket

        if not bucket:
            self._log.warning("dag_bucket_not_configured", filename=dag_filename)
            return

        from google.cloud import storage  # type: ignore[import]

        def _upload() -> None:
            client = storage.Client()
            bucket_name = bucket.replace("gs://", "").split("/")[0]
            prefix = "/".join(bucket.replace("gs://", "").split("/")[1:])
            blob_path = f"{prefix}/{dag_filename}" if prefix else f"dags/{dag_filename}"
            bucket_obj = client.bucket(bucket_name)
            blob = bucket_obj.blob(blob_path)
            blob.upload_from_string(dag_content, content_type="text/x-python")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _upload)
        self._log.info("dag_uploaded", filename=dag_filename, bucket=bucket)

    async def list_dags(self) -> list[dict[str, Any]]:
        """Return a list of all DAGs registered in Airflow."""
        url = f"{self._api_url}/dags?limit=100"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=self._auth()) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("dags", [])

    async def pause_dag(self, dag_id: str, is_paused: bool = True) -> bool:
        """Pause or unpause a DAG."""
        url = f"{self._api_url}/dags/{dag_id}"
        payload = {"is_paused": is_paused}
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, json=payload, auth=self._auth()) as resp:
                return resp.status == 200
