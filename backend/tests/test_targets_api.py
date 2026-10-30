"""Behavior tests for target and protected-value API workflows."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "sentinel-api"}


def test_create_retrieve_and_list_target_without_exposing_api_key(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    created_response = api_client.post("/targets", json=valid_target_payload)

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["name"] == "Support Assistant"
    assert created["has_api_key"] is True
    assert "api_key" not in created
    assert "fake-test-key" not in created_response.text

    retrieved_response = api_client.get(f"/targets/{created['id']}")
    listed_response = api_client.get("/targets")

    assert retrieved_response.status_code == 200
    assert retrieved_response.json() == created
    assert listed_response.status_code == 200
    assert listed_response.json() == [created]


def test_update_distinguishes_omitted_key_from_explicit_null(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]

    renamed = api_client.put(f"/targets/{target_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"
    assert renamed.json()["has_api_key"] is True

    cleared = api_client.put(f"/targets/{target_id}", json={"api_key": None})
    assert cleared.status_code == 200
    assert cleared.json()["has_api_key"] is False
    assert "api_key" not in cleared.json()


@pytest.mark.parametrize(
    ("change", "expected_fragment"),
    [
        ({"http_method": "GET"}, "Input should be 'POST'"),
        ({"endpoint_url": "not-a-url"}, "valid URL"),
        (
            {"endpoint_url": "https://user:pass@example.test/chat"},
            "embedded credentials",
        ),
        ({"request_template": []}, "valid dictionary"),
    ],
)
def test_invalid_target_configuration_is_rejected(
    api_client: TestClient,
    valid_target_payload: dict,
    change: dict,
    expected_fragment: str,
) -> None:
    payload = deepcopy(valid_target_payload)
    payload.update(change)

    response = api_client.post("/targets", json=payload)

    assert response.status_code == 422
    assert expected_fragment.lower() in response.text.lower()


def test_invalid_prompt_path_is_rejected_and_validation_echo_redacts_key(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    payload = deepcopy(valid_target_payload)
    payload["prompt_field"] = "payload.missing.content"
    payload["api_key"] = "DO_NOT_ECHO_THIS_KEY"

    response = api_client.post("/targets", json=payload)

    assert response.status_code == 422
    assert "prompt_field is invalid" in response.text
    assert "DO_NOT_ECHO_THIS_KEY" not in response.text
    assert "[REDACTED]" in response.text


def test_update_validates_merged_request_template_and_prompt_path(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]

    response = api_client.put(
        f"/targets/{target_id}",
        json={"request_template": {"message": ""}},
    )

    assert response.status_code == 422
    assert "prompt_field is invalid for request_template" in response.text


def test_protected_values_are_masked_and_can_be_deleted(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]
    protected_payload = {
        "name": "Fake API canary",
        "value": "TEST_SECRET_ABC123",
    }

    created_response = api_client.post(
        f"/targets/{target_id}/protected-values",
        json=protected_payload,
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["name"] == "Fake API canary"
    assert "value" not in created
    assert created["display_value"] != protected_payload["value"]
    assert protected_payload["value"] not in created_response.text

    listed = api_client.get(f"/targets/{target_id}/protected-values")
    assert listed.status_code == 200
    assert listed.json() == [created]

    deleted = api_client.delete(f"/protected-values/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api_client.get(f"/targets/{target_id}/protected-values").json() == []


def test_delete_target_and_missing_resources_use_expected_status_codes(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]

    response = api_client.delete(f"/targets/{target_id}")

    assert response.status_code == 204
    assert api_client.get(f"/targets/{target_id}").status_code == 404
    assert api_client.get("/targets/999/protected-values").status_code == 404
    assert api_client.delete("/protected-values/999").status_code == 404


def test_empty_or_null_target_updates_are_rejected(
    api_client: TestClient,
    valid_target_payload: dict,
) -> None:
    target_id = api_client.post("/targets", json=valid_target_payload).json()["id"]

    assert api_client.put(f"/targets/{target_id}", json={}).status_code == 422
    assert (
        api_client.put(f"/targets/{target_id}", json={"name": None}).status_code == 422
    )


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize(
    "change",
    [
        {"prompt_field": "payload.messages.².content"},
        {"response_field": "result..answer"},
    ],
)
def test_malformed_paths_are_validation_errors_on_create_and_update(
    api_client: TestClient, valid_target_payload: dict, method: str, change: dict
) -> None:
    if method == "POST":
        response = api_client.post("/targets", json={**valid_target_payload, **change})
    else:
        target = api_client.post("/targets", json=valid_target_payload).json()
        response = api_client.put(f"/targets/{target['id']}", json=change)
        assert api_client.get(f"/targets/{target['id']}").json() == target

    assert response.status_code == 422
    assert "fake-test-key" not in response.text
