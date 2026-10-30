"""Pure, versioned historical analysis of stored evidence; no target requests."""

from statistics import mean, median

from app.evaluators.metrics import summarize

ANALYSIS_VERSION = "history-v2"
MIN_REPEATS = 3
BEHAVIORAL = {"passed", "failed"}


def cached_judgment(result):
    return any(
        a.get("evaluator") == "llm_judge" and a.get("evidence", {}).get("cache_hit")
        for a in (result.assertion_results or [])
    )


def repeated_outcome(run, attack_id):
    result = keyed_results(run).get(attack_id)
    return (
        result.outcome
        if run.status == "completed" and result and not cached_judgment(result)
        else "untested"
    )


def keyed_results(run):
    keys = [(r.provenance or {}).get("id", f"legacy-{r.id}") for r in run.results]
    # Redaction may make two otherwise unique display IDs identical.
    if len(set(keys)) != len(keys):
        keys = [f"case-{index}" for index in range(len(run.results))]
    return dict(zip(keys, run.results))


def compatible(first, second):
    return bool(
        first.comparison_key
        and first.comparison_key == second.comparison_key
        and first.target_application_id == second.target_application_id
    )


def latency(results):
    values = [
        r.duration_ms
        for r in results
        if r.response_status is not None and r.outcome in BEHAVIORAL
    ]
    return {
        "sample_size": len(values),
        "mean_ms": round(mean(values), 2) if values else None,
        "median_ms": median(values) if values else None,
    }


def point(run, baseline):
    security = [r for r in run.results if r.category != "reliability"]
    return {
        "run_id": run.id,
        "created_at": run.created_at,
        "status": run.status,
        "versions": run.version_tags,
        "compatible": compatible(run, baseline),
        "metrics": run.metrics,
        "security_metrics": summarize(
            security, (run.pack_snapshot or {}).get("severity_weights")
        )
        if run.engine_version
        else None,
        "latency": latency(run.results),
    }


def compare_runs(baseline, candidate):
    old, new = keyed_results(baseline), keyed_results(candidate)
    shared = sorted(old.keys() & new.keys())
    is_compatible = compatible(baseline, candidate)
    pairs = (
        [
            key
            for key in shared
            if old[key].outcome in BEHAVIORAL and new[key].outcome in BEHAVIORAL
        ]
        if is_compatible
        else []
    )
    weights = (baseline.pack_snapshot or {}).get("severity_weights")

    def effect(keys):
        before = summarize([old[k] for k in keys], weights)["weighted_score"]
        after = summarize([new[k] for k in keys], weights)["weighted_score"]
        return {
            "sample_size": len(keys),
            "baseline_weighted_score": before,
            "candidate_weighted_score": after,
            "change_percentage_points": round(after - before, 2)
            if before is not None and after is not None
            else None,
        }

    coverage_changes = [
        {"attack_id": k, "baseline": old[k].outcome, "candidate": new[k].outcome}
        for k in shared
        if (old[k].outcome not in BEHAVIORAL or new[k].outcome not in BEHAVIORAL)
        and old[k].outcome != new[k].outcome
    ]
    flags = []
    if any(cached_judgment(r) for r in list(old.values()) + list(new.values())):
        flags.append("cached_judgments_are_not_fresh_samples")
    if not is_compatible:
        flags.append("incompatible_configuration")
    if baseline.status != "completed" or candidate.status != "completed":
        flags.append("incomplete_run")
    if len(pairs) < len(shared) or coverage_changes or old.keys() != new.keys():
        flags.append("changed_or_incomplete_coverage")
    if len(pairs) == 0:
        flags.append("no_paired_behavioral_samples")
    flags.append("single_run_observation_not_statistical_significance")
    return {
        "analysis_version": ANALYSIS_VERSION,
        "baseline_run_id": baseline.id,
        "candidate_run_id": candidate.id,
        "compatible": is_compatible,
        "flags": flags,
        "sample_sizes": {
            "baseline_planned": len(old),
            "candidate_planned": len(new),
            "paired_behavioral": len(pairs),
            "baseline_runs": 1,
            "candidate_runs": 1,
        },
        "added_attacks": sorted(new.keys() - old.keys()),
        "removed_attacks": sorted(old.keys() - new.keys()),
        "coverage_changes": coverage_changes,
        "regressions": [
            k
            for k in pairs
            if old[k].outcome == "passed" and new[k].outcome == "failed"
        ],
        "improvements": [
            k
            for k in pairs
            if old[k].outcome == "failed" and new[k].outcome == "passed"
        ],
        "execution_errors": [k for k in sorted(new) if new[k].outcome == "errored"],
        "effect": effect(pairs),
        "categories": {
            category: effect([k for k in pairs if new[k].category == category])
            for category in sorted({new[k].category for k in pairs})
        },
        "latency": {
            "paired_sample_size": sum(
                old[k].response_status is not None
                and new[k].response_status is not None
                for k in pairs
            ),
            "baseline": latency([old[k] for k in pairs]),
            "candidate": latency([new[k] for k in pairs]),
            "paired_mean_change_ms": round(
                mean(
                    [
                        new[k].duration_ms - old[k].duration_ms
                        for k in pairs
                        if old[k].response_status is not None
                        and new[k].response_status is not None
                    ]
                ),
                2,
            )
            if any(
                old[k].response_status is not None
                and new[k].response_status is not None
                for k in pairs
            )
            else None,
        },
        "baseline": point(baseline, baseline),
        "candidate": point(candidate, baseline),
    }


def repeated_regressions(baseline, runs):
    """Conservative descriptive replication, not an independence/significance claim."""
    base_tags = baseline.version_tags or {}
    versioned = any(base_tags.values())
    groups = {}
    for run in runs:
        if not compatible(baseline, run):
            continue
        tags = run.version_tags or {}
        if not any(tags.values()):
            continue
        key = tuple(sorted(tags.items()))
        groups.setdefault(key, []).append(run)
    base_group = groups.get(tuple(sorted(base_tags.items())), []) if versioned else []
    summaries = []
    for key, members in groups.items():
        if key == tuple(sorted(base_tags.items())):
            continue
        confirmed = []
        variable = []
        samples = {}
        for attack_id in keyed_results(baseline):
            before = [repeated_outcome(r, attack_id) for r in base_group]
            after = [repeated_outcome(r, attack_id) for r in members]
            clean_before = [v for v in before if v in BEHAVIORAL]
            clean_after = [v for v in after if v in BEHAVIORAL]
            enough = (
                len(clean_before) >= MIN_REPEATS and len(clean_after) >= MIN_REPEATS
            )
            samples[attack_id] = {
                "baseline": len(clean_before),
                "candidate": len(clean_after),
                "excluded": len(before)
                + len(after)
                - len(clean_before)
                - len(clean_after),
            }
            if (
                enough
                and len(clean_before) == len(before)
                and len(clean_after) == len(after)
                and set(before) == {"passed"}
                and set(after) == {"failed"}
            ):
                confirmed.append(attack_id)
            elif "failed" in after:
                variable.append(attack_id)
        summaries.append(
            {
                "versions": dict(key),
                "run_ids": [r.id for r in members],
                "baseline_run_ids": [r.id for r in base_group],
                "samples": samples,
                "repeated_regressions": confirmed,
                "needs_review": variable,
                "status": "insufficient_repeats"
                if len(base_group) < MIN_REPEATS or len(members) < MIN_REPEATS
                else "insufficient_behavioral_samples"
                if any(
                    sample["baseline"] < MIN_REPEATS
                    or sample["candidate"] < MIN_REPEATS
                    for sample in samples.values()
                )
                else "descriptive_only",
            }
        )
    return {
        "minimum_repeats_per_version": MIN_REPEATS,
        "baseline_run_ids": [r.id for r in base_group],
        "groups": summaries,
        "policy": "Separate runs are repeats; retries and attack cases are not independent replicates. Cached semantic judgments are excluded. Require distinct version tags and at least 3 behavioral observations per version, all baseline passes and all candidate failures, with no missing/error/incomplete-run observations. Review mixed results. No confidence or significance claim; target and judge nondeterminism and sampling dependence are unknown.",
    }
