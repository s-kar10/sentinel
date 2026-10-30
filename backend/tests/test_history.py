"""Synthetic regression, coverage, baseline identity and repeat-policy evidence."""

import time
from unittest.mock import patch

import pytest
from test_engine_v2 import engine_api, pack, spec  # noqa: F401
from test_jobs import claim, finish, result, target

from app.attacks.packs import AttackPack
from app.models import EvaluationRun, TargetApplication
from app.services.comparison import compare_runs, repeated_regressions
from app.services.history_service import HistoryService
from app.services.job_service import JobService
from app.services.target_client import TargetResponse


def completed(factory, tid, outcomes, version=None, config=None, latency=20):
    definition = config or pack(spec("exact_match", {"values": ["SAFE"]}))
    if config is None:
        definition["attacks"] = [
            {**definition["attacks"][0], "id": f"check-{i}"}
            for i in range(len(outcomes))
        ]
    with factory() as db:
        rid = (
            JobService(db)
            .submit(
                tid,
                attack_pack=AttackPack.model_validate(definition),
                versions={"application": version} if version else {},
            )
            .id
        )
    now = time.time() + 600 + rid * 10
    for index, outcome in enumerate(outcomes):
        lease = claim(factory, now + index)
        assert lease.run_id == rid
        finish(
            factory,
            lease,
            now + index + 0.1,
            data={
                **result(outcome),
                "response_status": 200 if outcome in {"passed", "failed"} else None,
                "duration_ms": latency,
            },
        )
    return rid


def test_cached_judgments_are_excluded_from_repeated_regressions(session_factory):
    tid = target(session_factory)
    before = [completed(session_factory, tid, ["passed"], "v1") for _ in range(3)]
    after = [completed(session_factory, tid, ["failed"], "v2") for _ in range(3)]
    with session_factory() as db:
        runs = [db.get(EvaluationRun, rid) for rid in before + after]
        assert repeated_regressions(runs[0], runs)["groups"][0][
            "repeated_regressions"
        ] == ["check-0"]
        runs[-1].results[0].assertion_results = [
            {"evaluator": "llm_judge", "evidence": {"cache_hit": True}}
        ]
        analysis = repeated_regressions(runs[0], runs)["groups"][0]
        assert analysis["repeated_regressions"] == []
        assert analysis["samples"]["check-0"] == {
            "baseline": 3,
            "candidate": 2,
            "excluded": 1,
        }
        assert analysis["status"] == "insufficient_behavioral_samples"
        assert (
            "cached_judgments_are_not_fresh_samples"
            in compare_runs(runs[0], runs[-1])["flags"]
        )


def test_api_baseline_immutable_and_regression(engine_api):  # noqa: F811
    client, tid, transport, _ = engine_api
    body = {"attack_pack": pack(spec("exact_match", {"values": ["SAFE"]}))}
    first = client.post(f"/targets/{tid}/evaluations", json=body).json()
    baseline = client.post(
        f"/targets/{tid}/baselines", json={"name": "release-1", "run_id": first["id"]}
    )
    assert baseline.status_code == 201
    bid = baseline.json()["id"]
    transport.send_prompt.return_value = TargetResponse("UNSAFE", 30, status_code=200)
    second = client.post(f"/targets/{tid}/evaluations", json=body).json()
    comparison = client.get(
        f"/evaluations/{second['id']}/comparison?baseline_id={bid}"
    ).json()
    assert comparison["regressions"] == ["check"]
    assert comparison["effect"]["change_percentage_points"] == -100
    assert comparison["latency"]["paired_mean_change_ms"] == 20
    assert comparison["sample_sizes"]["paired_behavioral"] == 1
    assert "single_run_observation_not_statistical_significance" in comparison["flags"]
    assert (
        client.post(
            f"/targets/{tid}/baselines",
            json={"name": "release-1", "run_id": second["id"]},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/targets/{tid}/baselines",
            json={"name": "release-1", "run_id": second["id"]},
        ).status_code
        == 405
    )
    assert client.get(f"/targets/{tid}/baselines").json()[0]["run_id"] == first["id"]


def test_coverage_errors_not_behavioral_regressions(session_factory):
    tid = target(session_factory)
    first = completed(session_factory, tid, ["passed", "passed", "failed"])
    second = completed(session_factory, tid, ["failed", "errored", "passed"])
    with session_factory() as db:
        analysis = compare_runs(
            db.get(EvaluationRun, first), db.get(EvaluationRun, second)
        )
    assert analysis["regressions"] == ["check-0"]
    assert analysis["improvements"] == ["check-2"]
    assert analysis["execution_errors"] == ["check-1"]
    assert analysis["effect"]["change_percentage_points"] == 0
    assert analysis["sample_sizes"]["paired_behavioral"] == 2
    assert analysis["coverage_changes"] == [
        {"attack_id": "check-1", "baseline": "passed", "candidate": "errored"}
    ]
    assert "changed_or_incomplete_coverage" in analysis["flags"]
    assert analysis["candidate"]["metrics"]["coverage"] == 66.67


def test_changed_configuration_added_checks_and_legacy_are_flagged(session_factory):
    tid = target(session_factory)
    first = completed(session_factory, tid, ["passed"])
    second = completed(session_factory, tid, ["failed", "failed"])
    with session_factory() as db:
        old, new = db.get(EvaluationRun, first), db.get(EvaluationRun, second)
        analysis = compare_runs(old, new)
        assert not analysis["compatible"] and analysis["regressions"] == []
        assert analysis["added_attacks"] == ["check-1"]
        assert analysis["effect"]["change_percentage_points"] is None
        old.comparison_key = None
        assert not compare_runs(old, old)["compatible"]


def test_repeats_detect_known_regression_and_report_window(session_factory):
    tid = target(session_factory)
    before = [completed(session_factory, tid, ["passed"], "v1") for _ in range(3)]
    after = [
        completed(session_factory, tid, ["failed"], "v2", latency=40) for _ in range(3)
    ]
    with session_factory() as db:
        service = HistoryService(db)
        baseline = service.create_baseline(tid, before[0], "stable")
        data = service.analytics(tid, baseline.id)
        assert len(data["points"]) == 6
        assert data["repetition"]["groups"][0]["repeated_regressions"] == ["check-0"]
        assert data["repetition"]["groups"][0]["samples"]["check-0"] == {
            "baseline": 3,
            "candidate": 3,
            "excluded": 0,
        }
        assert data["repetition"]["groups"][0]["run_ids"] == after
        assert data["points"][-1]["latency"]["sample_size"] == 1
        assert (
            data["points"][-1]["metrics"]["categories"]["reliability"]["weighted_score"]
            == 0
        )
        assert data["points"][-1]["security_metrics"]["weighted_score"] is None
        assert data["through_run_id"] == after[-1]
        bid = baseline.id
    completed(session_factory, tid, ["passed"], "v2")
    with session_factory() as db:
        service = HistoryService(db)
        replay = service.analytics(tid, bid, through_run_id=data["through_run_id"])
        assert replay == data
        current = service.analytics(tid, bid)
        assert current["repetition"]["groups"][0]["repeated_regressions"] == []
        assert current["repetition"]["groups"][0]["needs_review"] == ["check-0"]
        bounded = service.analytics(tid, bid, limit=2)
        assert bounded["truncated"] and len(bounded["points"]) == 2
        assert bounded["repetition"]["groups"][0]["status"] == "insufficient_repeats"


def test_execution_errors_and_insufficient_repeats_prevent_repeated_claim(
    session_factory,
):
    tid = target(session_factory)
    before = [completed(session_factory, tid, ["passed"], "v1") for _ in range(3)]
    completed(session_factory, tid, ["failed"], "v2")
    with session_factory() as db:
        service = HistoryService(db)
        bid = service.create_baseline(tid, before[0], "stable").id
        group = service.analytics(tid, bid)["repetition"]["groups"][0]
        assert group["status"] == "insufficient_repeats"
        assert group["repeated_regressions"] == []
    for outcome in ("failed", "failed", "errored"):
        completed(session_factory, tid, [outcome], "v2")
    with session_factory() as db:
        group = HistoryService(db).analytics(tid, bid)["repetition"]["groups"][0]
        assert group["repeated_regressions"] == []
        assert group["samples"]["check-0"]["excluded"] == 1


def test_frozen_target_context_and_version_labels(session_factory):
    tid = target(session_factory)
    first = completed(session_factory, tid, ["passed"], "v1")
    with session_factory() as db:
        old_key = db.get(EvaluationRun, first).comparison_key
        db.get(TargetApplication, tid).response_field = "different"
        db.commit()
    second = completed(session_factory, tid, ["passed"], "v2")
    with session_factory() as db:
        assert db.get(EvaluationRun, first).comparison_key == old_key
        assert db.get(EvaluationRun, first).version_tags == {"application": "v1"}
        assert not compare_runs(
            db.get(EvaluationRun, first), db.get(EvaluationRun, second)
        )["compatible"]


def test_baseline_rejects_partial_errors_and_foreign_target(session_factory):
    tid = target(session_factory)
    rid = completed(session_factory, tid, ["errored"], "v1")
    other = target(session_factory)
    with session_factory() as db:
        service = HistoryService(db)
        for target_id in (tid, other):
            with pytest.raises(Exception, match="full coverage"):
                service.create_baseline(target_id, rid, "bad")
        run = db.get(EvaluationRun, rid)
        run.status = "running"
        assert "incomplete_run" in compare_runs(run, run)["flags"]


def test_api_validation_redaction_and_no_network_during_analysis(engine_api):  # noqa: F811
    client, tid, transport, _ = engine_api
    response = client.post(
        f"/targets/{tid}/evaluation-jobs", json={"versions": {"unknown": "value"}}
    )
    assert response.status_code == 422
    body = {"attack_pack": pack(spec("status_code", {"allowed": [200]}))}
    rid = client.post(f"/targets/{tid}/evaluations", json=body).json()["id"]
    bid = client.post(
        f"/targets/{tid}/baselines", json={"run_id": rid, "name": "test"}
    ).json()["id"]
    with patch.object(
        transport, "send_prompt", side_effect=AssertionError("Analysis must be offline")
    ):
        assert (
            client.get(
                f"/targets/{tid}/analytics?baseline_id={bid}&limit=101"
            ).status_code
            == 422
        )
        analysis = client.get(f"/targets/{tid}/analytics?baseline_id={bid}")
        assert analysis.status_code == 200
        assert "fake-test-key" not in analysis.text
        assert "comparison_key" not in analysis.text
        assert (
            client.get(f"/evaluations/{rid}/comparison?baseline_id={bid}").status_code
            == 200
        )


def test_incomplete_tagged_runs_are_visible_in_repeat_sample_exclusions(
    session_factory,
):
    tid = target(session_factory)
    before = [completed(session_factory, tid, ["passed"], "v1") for _ in range(3)]
    for _ in range(3):
        completed(session_factory, tid, ["failed"], "v2")
    with session_factory() as db:
        definition = pack(spec("exact_match", {"values": ["SAFE"]}))
        definition["attacks"][0]["id"] = "check-0"
        run = JobService(db).submit(
            tid,
            attack_pack=AttackPack.model_validate(definition),
            versions={"application": "v2"},
        )
        JobService(db).cancel(run.id)
        history = HistoryService(db)
        bid = history.create_baseline(tid, before[0], "stable").id
        group = history.analytics(tid, bid)["repetition"]["groups"][0]
        assert group["samples"]["check-0"] == {
            "baseline": 3,
            "candidate": 3,
            "excluded": 1,
        }
        assert group["repeated_regressions"] == []
        assert run.id in group["run_ids"]
