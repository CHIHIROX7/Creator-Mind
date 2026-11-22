from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import sources
from app.db.session import get_db
from app.main import app

ENDPOINT = "/api/v1/sources"


@pytest.fixture
def library(monkeypatch):
    db = AsyncMock(spec=AsyncSession)
    records = {}
    objects = {}

    def add(source):
        source.created_at = datetime.now(UTC)
        records[source.id] = source

    def put(source, file):
        objects[source.object_key] = file.read()

    db.add.side_effect = add
    db.get.side_effect = lambda _model, asset_id: records.get(asset_id)
    db.scalars.return_value = Mock()
    db.scalars.return_value.all.return_value = []
    put_object = Mock(side_effect=put)
    discard_object = Mock(side_effect=lambda key: objects.pop(key, None))
    monkeypatch.setattr(sources, "put_source_object", put_object)
    monkeypatch.setattr(sources, "discard_source_object", discard_object)
    monkeypatch.setattr(sources.settings, "environment", "test")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, records, objects, put_object, discard_object
    finally:
        app.dependency_overrides.pop(get_db)


def test_uploaded_file_is_available_by_source_id(library):
    client, db, records, objects, _, _ = library
    response = client.post(
        ENDPOINT,
        files={"file": ("参考.md", b"# Notes", "application/octet-stream")},
        data={"source_url": "https://example.com/notes"},
    )

    assert response.status_code == 201
    asset = response.json()
    source = next(iter(records.values()))
    assert asset["id"] == str(source.id)
    assert asset["filename"] == "参考.md"
    assert asset["source_url"] == "https://example.com/notes"
    assert asset["size_bytes"] == len(b"# Notes")
    assert asset["content_type"] == "text/markdown"
    assert "object_key" not in asset
    assert objects[source.object_key] == b"# Notes"
    db.commit.assert_awaited_once()

    assert client.get(f"{ENDPOINT}/{asset['id']}").json() == asset
    assert client.get(f"{ENDPOINT}/{uuid4()}").status_code == 404
    db.scalars.return_value.all.return_value = [source]
    assert client.get(ENDPOINT, params={"limit": 1, "offset": 0}).json() == [asset]


@pytest.mark.parametrize(
    ("filename", "data", "source_url", "expected"),
    [
        ("sample.exe", b"file", None, 415),
        ("sample.pdf", b"wrong", None, 415),
        ("sample.txt", b"", None, 422),
        ("sample.txt", b"valid", "javascript:alert(1)", 422),
        ("sample.txt", b"too long", None, 413),
    ],
)
def test_invalid_files_are_rejected_before_storage(
    library, monkeypatch, filename, data, source_url, expected
):
    client, db, _, _, put_object, _ = library
    monkeypatch.setattr(sources, "MAX_SOURCE_BYTES", 5)
    response = client.post(
        ENDPOINT,
        files={"file": (filename, data)},
        data={"source_url": source_url} if source_url else None,
    )
    assert response.status_code == expected
    db.add.assert_not_called()
    put_object.assert_not_called()


def test_storage_failure_does_not_commit_metadata(library):
    client, db, _, _, put_object, discard_object = library
    put_object.side_effect = EndpointConnectionError(endpoint_url="http://localhost:19000")
    assert client.post(ENDPOINT, files={"file": ("sample.txt", b"hello")}).status_code == 503
    db.commit.assert_not_awaited()
    discard_object.assert_called_once()


def test_database_rejection_cleans_up_the_original(library):
    client, db, _, objects, _, discard_object = library
    db.commit.side_effect = IntegrityError("commit", {}, ValueError("rejected"))
    assert client.post(ENDPOINT, files={"file": ("sample.txt", b"hello")}).status_code == 503
    discard_object.assert_called_once()
    assert not objects


def test_production_rejects_requests_before_database_access(library, monkeypatch):
    client, db, _, _, _, _ = library
    monkeypatch.setattr(sources.settings, "environment", "production")
    assert client.get(ENDPOINT).status_code == 503
    db.scalars.assert_not_awaited()
