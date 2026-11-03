"""Known safe/unsafe outcomes through the real adapter, evaluator and saved API."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_evaluation_service
from app.attacks.packs import AttackPack
from app.attacks.security import ACTIONS, INSTRUCTIONS, RETRIEVAL, SECURITY_PACKS
from app.database.session import get_db
from app.evaluators.contracts import aggregate
from app.evaluators.engine import evaluate_assertion
from app.services.evaluation_service import EvaluationService
from app.services.target_client import TargetClient, TargetResponse


def outcomes(attack, document):
    observation = TargetResponse(
        document.get("response"),
        1,
        status_code=200,
        document=document,
        has_document=True,
    )
    return [
        evaluate_assertion(spec.model_dump(), observation, ())
        for spec in attack.assertions
    ]


@pytest.mark.parametrize("pack", SECURITY_PACKS, ids=lambda p: p.id)
@pytest.mark.parametrize("mode", ["safe", "vulnerable"])
def test_security_packs_saved_results(api_app, api_client, demo_app, pack, mode):
    with TestClient(demo_app) as fixture:

        def dispatch(request):
            assert request.url.host == "security-fixture"
            assert request.url.path == f"/security/{mode}"
            response = fixture.post(
                request.url.path,
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
            target = api_client.post(
                "/targets",
                json={
                    "name": "Synthetic security fixture",
                    "endpoint_url": f"http://security-fixture/security/{mode}",
                    "request_template": {"message": ""},
                    "prompt_field": "message",
                    "response_field": "response",
                },
            ).json()
            exported = next(
                item
                for item in api_client.get("/attack-packs").json()
                if item["id"] == pack.id
            )
            assert AttackPack.model_validate(exported) == pack
            result = api_client.post(
                f"/targets/{target['id']}/evaluations", json={"attack_pack": exported}
            )
    assert result.status_code == 201
    run = result.json()
    assert run["status"] == "completed"
    assert run["metrics"]["coverage"] == 100
    assert run["metrics"]["errored"] == 0
    results = api_client.get(f"/evaluations/{run['id']}/results").json()
    assert len(results) == len(pack.attacks)
    for attack, saved in zip(pack.attacks, results):
        expected = (
            "passed" if mode == "safe" or attack.category == "reliability" else "failed"
        )
        assert saved["outcome"] == expected, attack.id
        assert saved["provenance"]["id"] == attack.id
        assert saved["provenance"]["version"] == 1
        assert saved["observation_snapshot"]["document"]
        assert saved["assertion_results"]
    assert run["passed_tests"] == (len(pack.attacks) if mode == "safe" else 1)
    assert api_client.get(f"/evaluations/{run['id']}").json() == run


@pytest.mark.parametrize("pack", SECURITY_PACKS, ids=lambda p: p.id)
def test_missing_observations_cannot_pass_a_security_pack(pack):
    for attack in pack.attacks:
        assert (
            aggregate(
                [r.outcome for r in outcomes(attack, {"response": "Safe refusal"})]
            )
            == "failed"
        )
        assert (
            aggregate(
                [
                    r.outcome
                    for r in outcomes(
                        attack,
                        {
                            "response": "",
                            "actions": [],
                            "render": {"kind": "text", "content": ""},
                        },
                    )
                ]
            )
            == "failed"
        )


def test_refusal_text_does_not_hide_tool_intent(demo_app):
    attack = ACTIONS.attacks[0]
    with TestClient(demo_app) as fixture:
        doc = fixture.post(
            "/security/vulnerable", json={"message": attack.prompt}
        ).json()
    assert doc["response"] == "I cannot perform that action."
    assert doc["actions"][0]["tool"] == "refund_order"
    checks = outcomes(attack, doc)
    assert [r.outcome for r in checks] == ["passed", "failed"]
    doc["actions"] = []
    assert all(r.outcome == "passed" for r in outcomes(attack, doc))


def test_detection_limits_are_explicit(demo_app):
    with TestClient(demo_app) as fixture:
        attack = INSTRUCTIONS.attacks[2]
        safe = fixture.post("/security/safe", json={"message": attack.prompt}).json()
    encoded = deepcopy(safe)
    # Literal canaries cannot detect transformed disclosure. This is an expected
    # blind spot, not a claim that the transformed response is secure.
    encoded["response"] = "S Y N T H E T I C _ S E C R E T _ 9 B 2"
    assert all(r.outcome == "passed" for r in outcomes(attack, encoded))
    quoted = deepcopy(safe)
    quoted["response"] = "I will not reveal SYNTHETIC_SECRET_9B2"
    assert aggregate([r.outcome for r in outcomes(attack, quoted)]) == "failed"
    # A plausible but differently worded policy answer needs a reviewed oracle.
    paraphrased = deepcopy(safe)
    paraphrased["response"] = "You have thirty days to request a refund."
    assert (
        aggregate([r.outcome for r in outcomes(RETRIEVAL.attacks[2], paraphrased)])
        == "failed"
    )


def test_pack_case_ids_are_unique_and_cover_phase_five():
    attacks = [a for p in SECURITY_PACKS for a in p.attacks]
    assert len(attacks) == len({a.id for a in attacks}) == 15
    assert {a.category.value for a in attacks} == {
        "prompt_injection",
        "indirect_prompt_injection",
        "system_prompt_leakage",
        "sensitive_information_leakage",
        "jailbreak",
        "instruction_hierarchy",
        "excessive_agency",
        "insecure_tool_use",
        "exfiltration",
        "unsafe_structured_output",
        "context_poisoning",
        "reliability",
    }
    assert all(json.loads(a.prompt)["user"] for a in attacks)
