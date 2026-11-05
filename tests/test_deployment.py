from k8s.render import manifests


def test_each_bank_mounts_only_its_data_and_workloads_have_health_and_limits():
    resources = manifests(5)
    deployments = [r for r in resources if r["kind"] == "Deployment"]
    assert len(deployments) == 6
    for deployment in deployments:
        name = deployment["metadata"]["name"]
        spec = deployment["spec"]["template"]["spec"]
        container = spec["containers"][0]
        assert spec["automountServiceAccountToken"] is False
        assert container["resources"]["limits"]["memory"] == "1Gi"
        assert container["readinessProbe"]["grpc"]["port"] == 9095
        if name.startswith("bank-"):
            assert spec["volumes"] == [
                {
                    "name": "data",
                    "hostPath": {"path": f"/mnt/bank-fl/{name}", "type": "Directory"},
                }
            ]


def test_weekly_retraining_never_overlaps_and_needs_no_data_mounts():
    (cronjob,) = [r for r in manifests(3) if r["kind"] == "CronJob"]
    assert cronjob["spec"]["schedule"] == "0 2 * * 0"
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["automountServiceAccountToken"] is False
    assert "volumes" not in pod
    assert pod["containers"][0]["command"][:3] == ["python", "-m", "app.scheduled"]
