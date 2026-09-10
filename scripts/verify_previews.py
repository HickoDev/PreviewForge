"""Real ApplicationSet acceptance with synthetic PR provider state; no remote publication."""

import json
import secrets
import sys
from datetime import UTC, datetime

import ci
import platform_local as p
import preview_state as s
import previews as v


def expect(condition, message):
    if not condition:
        raise RuntimeError(message)


def provider(number, image, status="open"):
    return {
        "number": number,
        "state": status,
        "headSha": image["sourceSha"],
        "repository": s.REPOSITORY,
        "headRepository": s.REPOSITORY,
        "author": "HickoDev",
    }


def save_provider(values):
    current = json.loads(v.PROVIDER.read_text()) if v.PROVIDER.exists() else {}
    current.update({str(key): value for key, value in values.items()})
    v.PROVIDER.write_text(json.dumps(current, indent=2) + "\n")


def receipt(number, image, event="pull_request"):
    return {
        **image,
        "repository": s.REPOSITORY,
        "event": event,
        "pr": number,
        "conclusion": "success",
        "published": True,
        "runId": number,
        "attempt": 1,
    }


def image_revision(label):
    (p.SOURCE / "previewforge-demo/app/release_fixture.py").write_text(
        f'RELEASE = "{label}-{secrets.token_hex(6)}"\n'
    )
    sha = p.commit("Synthetic " + label + " source", ["previewforge-demo/app/release_fixture.py"])
    return p.load_image(sha)


def version(name, image, port):
    with p.forward(namespace=name, port=port):
        code, value = p.http("/version", port=port)
        expect(
            code == 200 and value == {"environment": name, "source_sha": image["sourceSha"]},
            "Wrong running source/environment",
        )
        expect(p.http("/health/ready", port=port)[0] == 200, "Environment not ready")
        return p.http("/tasks", port=port)[1]


def verify():
    expect(not v.desired(), "Close existing local previews before running acceptance")
    results = {
        "startedAt": datetime.now(UTC).isoformat(),
        "scope": "local kind/ApplicationSet + synthetic PR provider; no GitHub/GHCR delivery",
        "checks": [],
    }

    def passed(name, **details):
        print("PASS: " + name, flush=True)
        results["checks"].append({"name": name, "at": datetime.now(UTC).isoformat(), **details})

    ci.test()
    p.run(sys.executable, "-m", "unittest", "discover", "-s", p.ROOT / "tests/platform")
    baseline = p.load_image(p.snapshot())
    p.wait_staging(p.deploy_record(baseline, "Verify Milestone 3 chart on persistent staging"))
    staging_pvc = p.get("pvc", "demo-postgres")["metadata"]["uid"]
    staging_tasks = version("staging", baseline, 18040)
    passed(
        "Application tests and platform regressions; staging baseline healthy",
        stagingPvcUid=staging_pvc,
    )

    number_a = 900_000_000 + secrets.randbelow(90_000_000)
    number_b = number_a + 1
    name_a, name_b = s.preview_name(number_a), s.preview_name(number_b)
    store = v.LocalStore()
    states = {}
    try:
        image_a = baseline
        image_b = image_revision("PR-B")
        states = {number_a: provider(number_a, image_a), number_b: provider(number_b, image_b)}
        save_provider(states)
        for number, image in ((number_a, image_a), (number_b, image_b)):
            s.transact(
                store,
                lambda records, number=number, image=image: s.update_build(
                    records, receipt(number, image), v.get_fixture_pr(number), local=True
                ),
            )
        v.reconcile(apply=True)
        for name, image in ((name_a, image_a), (name_b, image_b)):
            v.wait_preview(name, image)
        tasks_a = version(name_a, image_a, 18042)
        tasks_b = version(name_b, image_b, 18043)
        expect(len(tasks_a) == len(tasks_b) == 3, "Each preview must seed three synthetic tasks")
        with p.forward(namespace=name_a, port=18042):
            code, task_a = p.http("/tasks", "POST", {"title": "Only in preview A"}, port=18042)
            expect(code == 201, "Could not create preview A task")
        with p.forward(namespace=name_b, port=18043):
            code, task_b = p.http("/tasks", "POST", {"title": "Only in preview B"}, port=18043)
            expect(code == 201, "Could not create preview B task")
        pvc_a, pvc_b = p.get("pvc", "demo-postgres", name_a), p.get("pvc", "demo-postgres", name_b)
        expect(pvc_a["spec"]["volumeName"] != pvc_b["spec"]["volumeName"], "Previews share a PV")
        for pvc in (pvc_a, pvc_b):
            expect(
                p.get("pv", pvc["spec"]["volumeName"])["spec"]["persistentVolumeReclaimPolicy"]
                == "Delete",
                "Preview storage must be disposable",
            )
        expect(
            task_a["id"] not in {x["id"] for x in version(name_b, image_b, 18043)},
            "Data leaked from A to B",
        )
        expect(
            task_b["id"] not in {x["id"] for x in version(name_a, image_a, 18042)},
            "Data leaked from B to A",
        )
        deployment_b = p.get("deployment", "demo-api", name_b)["spec"]["template"]
        passed(
            "Two simultaneous ApplicationSet previews, seeded isolated databases and distinct disposable PVs",
            previewA=name_a,
            previewB=name_b,
        )

        updated_a = image_revision("PR-A-update")
        states[number_a] = provider(number_a, updated_a)
        save_provider(states)
        s.transact(
            store,
            lambda records: s.update_build(
                records, receipt(number_a, updated_a), v.get_fixture_pr(number_a), local=True
            ),
        )
        v.wait_preview(name_a, updated_a)
        expect(
            task_a["id"] in {x["id"] for x in version(name_a, updated_a, 18042)},
            "A update lost its task",
        )
        expect(
            p.get("deployment", "demo-api", name_b)["spec"]["template"] == deployment_b,
            "Updating A changed B's pod template",
        )
        expect(task_b["id"] in {x["id"] for x in version(name_b, image_b, 18043)}, "B lost data")
        passed(
            "PR A update changes its image/source only and retains both databases",
            sourceA=updated_a["sourceSha"],
            sourceB=image_b["sourceSha"],
        )

        revision = store.head()
        for bad in (
            receipt(number_a, image_a),
            {**receipt(number_a, updated_a), "conclusion": "failure"},
            {**receipt(number_a, updated_a), "published": False},
        ):
            _, changed = s.transact(
                store,
                lambda records, bad=bad: s.update_build(
                    records, bad, v.get_fixture_pr(number_a), local=True
                ),
            )
            expect(not changed and store.head() == revision, "Rejected build mutated Git")
        expect(
            task_a["id"] in {x["id"] for x in version(name_a, updated_a, 18042)},
            "Rejected build affected API",
        )
        passed(
            "Stale, failed and unpublished completions leave Git and the running preview unchanged"
        )

        states[number_a]["state"] = "closed"
        save_provider(states)
        s.transact(store, lambda records: s.prune_records(records, v.get_fixture_pr, local=True))
        v.reconcile(apply=False)
        v.reconcile(apply=True)
        v.reconcile(apply=True)  # Interrupted/retried cleanup is idempotent.
        expect(
            not v.optional("namespace", name_a) and not v.optional("application", name_a),
            "A resources remain",
        )
        expect(not v.optional("pv", pvc_a["spec"]["volumeName"]), "A PV remains")
        expect(
            task_b["id"] in {x["id"] for x in version(name_b, image_b, 18043)},
            "Closing A affected B",
        )
        expect(
            version("staging", baseline, 18040) == staging_tasks, "Closing A affected staging data"
        )
        _, changed = s.transact(
            store,
            lambda records: s.update_build(
                records, receipt(number_a, updated_a), v.get_fixture_pr(number_a), local=True
            ),
        )
        expect(not changed and name_a not in v.desired(), "Late build recreated closed A")
        passed(
            "Closing A cascades workloads/PVC/PV then removes its namespace; B and staging survive; late completion rejected"
        )

        main_image = image_revision("main-after-merge")
        main_state = {
            "repository": s.REPOSITORY,
            "branch": "main",
            "headSha": main_image["sourceSha"],
        }
        revision, _ = s.transact(
            store,
            lambda records: s.update_build(
                records, receipt(number_a, main_image, "push"), main_state, local=True
            ),
        )
        p.wait_staging(revision)
        expect(
            main_image["sourceSha"] != updated_a["sourceSha"],
            "Main identity must differ from PR source",
        )
        expect(
            version("staging", main_image, 18040) == staging_tasks, "Main update lost staging data"
        )
        expect(
            p.get("pvc", "demo-postgres")["metadata"]["uid"] == staging_pvc,
            "Main update replaced staging PVC",
        )
        passed(
            "Successful simulated main build deploys its own source SHA and retains staging PVC/tasks",
            mainSource=main_image["sourceSha"],
            mainDigest=main_image["image"]["digest"],
        )

        # Deliberately miss the close event: only the periodic-style reconciler sees it.
        states[number_b]["state"] = "closed"
        save_provider(states)
        before = store.snapshot()[1]
        plan = s.prune_records(before, v.get_fixture_pr, local=True)
        expect(
            s.PREFIX + name_b + ".json" in before and s.PREFIX + name_b + ".json" not in plan,
            "Missed-event dry-run incorrect",
        )
        expect(store.snapshot()[1] == before, "Dry run mutated Git")
        s.transact(store, lambda records: s.prune_records(records, v.get_fixture_pr, local=True))
        # Simulate interruption after Git commit, before namespace cleanup.
        v.reconcile(apply=True)
        expect(not v.optional("pv", pvc_b["spec"]["volumeName"]), "B PV remains")
        expect(
            version("staging", main_image, 18040) == staging_tasks,
            "Orphan cleanup affected staging",
        )
        passed(
            "Missed-close reconciliation and resumed cleanup remove B fully; dry-run is read-only; staging stays functional"
        )
        results["status"] = "passed"
    finally:
        # Delete only this run's synthetic records; never broad-delete cluster resources.
        for number in states:
            states[number]["state"] = "closed"
        save_provider(states)
        paths = {s.PREFIX + name_a + ".json", s.PREFIX + name_b + ".json"}
        s.transact(
            store, lambda records: {k: value for k, value in records.items() if k not in paths}
        )
        v.reconcile(apply=True)
        results["completedAt"] = datetime.now(UTC).isoformat()
        (p.RUNTIME / "milestone-3-verification.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )
    print(
        "All local Milestone 3 acceptance checks passed. GitHub/GHCR delivery remains untested.",
        flush=True,
    )
