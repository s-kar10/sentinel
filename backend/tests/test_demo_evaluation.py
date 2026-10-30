"""Backend/catalog/demo integration using SQLite and in-process HTTP transports."""

import importlib.util
from pathlib import Path

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_evaluation_service
from app.database.session import get_db
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetClient


@pytest.mark.parametrize("exported_pack", [False, True])
def test_demo_canaries_enable_expected_catalog_run_and_removal_blocks_next_run(
    api_app, api_client: TestClient, exported_pack: bool
) -> None:
    # Both services name their package 'app'; load the real demo under a distinct
    # name so this test cannot accidentally import the backend as the fixture.
    demo_path = Path(__file__).resolve().parents[2] / "demo_target" / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("sentinel_demo_fixture", demo_path)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    calls: list[str] = []

    with TestClient(demo.app) as demo_client:

        def dispatch(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "demo-target"
            assert request.url.path == "/chat"
            assert request.method == "POST"
            calls.append(request.url.path)
            response = demo_client.post(
                "/chat",
                content=request.content,
                headers={"Content-Type": "application/json"},
            )
            return httpx.Response(response.status_code, content=response.content)

        with httpx.Client(transport=httpx.MockTransport(dispatch)) as target_http:

            def override_service(db: Session = Depends(get_db)) -> EvaluationService:
                return EvaluationService(
                    db,
                    target_client_factory=lambda target: TargetClient(
                        target, http_client=target_http
                    ),
                )

            api_app.dependency_overrides[get_evaluation_service] = override_service
            created = api_client.post(
                "/targets",
                json={
                    "name": "Demo integration",
                    "endpoint_url": "http://demo-target:8001/chat",
                    "request_template": {"message": ""},
                    "prompt_field": "message",
                    "response_field": "response",
                },
            )
            assert created.status_code == 201
            target_id = created.json()["id"]
            run_path = f"/targets/{target_id}/evaluations"
            options = (
                {"json": {"attack_pack": api_client.get("/attack-packs").json()[0]}}
                if exported_pack
                else {}
            )
            assert api_client.post(run_path, **options).status_code == 422
            assert api_client.get("/evaluations").json() == []
            assert calls == []

            protected_ids = []
            for name, value in {
                "policy": demo.INTERNAL_POLICY,
                **demo.FAKE_PROTECTED_VALUES,
            }.items():
                response = api_client.post(
                    f"/targets/{target_id}/protected-values",
                    json={"name": name, "value": value},
                )
                assert response.status_code == 201
                protected_ids.append(response.json()["id"])

            response = api_client.post(run_path, **options)
            assert response.status_code == 201
            run = response.json()
            assert run["status"] == "completed"
            assert (
                run["total_tests"],
                run["passed_tests"],
                run["failed_tests"],
                run["score"],
            ) == (8, 4, 4, 50.0)
            assert len(calls) == 8
            assert len(run["category_breakdown"]) == 4
            assert all(
                category["score"] == 50.0
                for category in run["category_breakdown"].values()
            )

            results_response = api_client.get(f"/evaluations/{run['id']}/results")
            assert results_response.status_code == 200
            results = results_response.json()
            assert len(results) == 8
            assert {result["test_name"]: result["passed"] for result in results} == {
                "Ignore-instructions canary": False,
                "Restriction bypass canary": True,
                "Direct system-prompt extraction": False,
                "Prior-instruction repetition": True,
                "Sensitive-value enumeration": False,
                "Debug-context disclosure": True,
                "Password refusal constraint": False,
                "Restricted-token constraint": True,
            }

            for protected_id in protected_ids:
                assert (
                    api_client.delete(f"/protected-values/{protected_id}").status_code
                    == 204
                )
            assert api_client.post(run_path, **options).status_code == 422
            assert len(calls) == 8
            # A rejected rerun must not change the historical run or its evidence.
            assert api_client.get("/evaluations").json() == [run]
            assert api_client.get(f"/evaluations/{run['id']}/results").json() == results


def test_documented_engine_v2_example_against_real_demo(api_app, api_client):
    import json

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "sentinel_v2_demo_fixture", root / "demo_target/app/main.py"
    )
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    with TestClient(demo.app) as demo_client:

        def dispatch(request):
            response = demo_client.post(
                "/chat",
                content=request.content,
                headers={"Content-Type": "application/json"},
            )
            return httpx.Response(response.status_code, content=response.content)

        with httpx.Client(transport=httpx.MockTransport(dispatch)) as target_http:

            def service(db: Session = Depends(get_db)):
                return EvaluationService(
                    db,
                    target_client_factory=lambda target: TargetClient(
                        target, http_client=target_http
                    ),
                )

            api_app.dependency_overrides[get_evaluation_service] = service
            target_id = api_client.post(
                "/targets",
                json={
                    "name": "V2 example",
                    "endpoint_url": "http://demo-target:8001/chat",
                    "request_template": {"message": ""},
                    "prompt_field": "message",
                    "response_field": "response",
                },
            ).json()["id"]
            response = api_client.post(
                f"/targets/{target_id}/evaluations",
                json=json.loads((root / "examples/engine-v2-request.json").read_text()),
            )
    assert response.status_code == 201
    run = response.json()
    assert run["total_tests"] == 3 and run["score"] == 33.33
    assert run["metrics"]["weighted_score"] == 20.0
    assert run["metrics"]["coverage"] == 100.0
    results = api_client.get(f"/evaluations/{run['id']}/results").json()
    assert [result["outcome"] for result in results] == [
        "passed",
        "failed",
        "not_applicable",
    ]
