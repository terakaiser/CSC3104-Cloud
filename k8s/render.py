"""Render the same small deployment for three or five banks."""

import argparse
from pathlib import Path

import yaml


def manifests(banks=3, image="bank-fl:0.1.0", host_data="/mnt/bank-fl"):
    namespace = "bank-fl"
    documents = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}},
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": "results", "namespace": namespace},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "1Gi"}},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "coordinator", "namespace": namespace},
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "coordinator"},
                "ports": [
                    {"name": "fleet", "port": 9092, "targetPort": 9092},
                    {"name": "control", "port": 9093, "targetPort": 9093},
                ],
            },
        },
    ]
    for index in range(banks + 1):
        coordinator = index == 0
        name = "coordinator" if coordinator else f"bank-{index}"
        command = ["flower-superlink" if coordinator else "flower-supernode", "--insecure"]
        command += ["--health-server-address", "0.0.0.0:9095"]
        if coordinator:
            command += ["--serverappio-api-address", "127.0.0.1:9091"]
            volumes = [
                {
                    "name": "manifest",
                    "hostPath": {"path": host_data + "/manifest.json", "type": "File"},
                },
                {"name": "results", "persistentVolumeClaim": {"claimName": "results"}},
            ]
            mounts = [
                {"name": "manifest", "mountPath": "/data/manifest.json", "readOnly": True},
                {"name": "results", "mountPath": "/results"},
            ]
        else:
            command += [
                "--superlink",
                "coordinator:9092",
                "--clientappio-api-address",
                "127.0.0.1:9094",
                "--node-config",
                f'bank-id="{name}"',
            ]
            volumes = [
                {"name": "data", "hostPath": {"path": host_data + f"/{name}", "type": "Directory"}}
            ]
            mounts = [{"name": "data", "mountPath": "/data", "readOnly": True}]
        documents.append(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name, "namespace": namespace},
                "spec": {
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name, "project": "bank-fl"}},
                        "spec": {
                            "automountServiceAccountToken": False,
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "runAsGroup": 10001,
                                "fsGroup": 10001,
                            },
                            "containers": [
                                {
                                    "name": name,
                                    "image": image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": command,
                                    "volumeMounts": mounts,
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "250m", "memory": "256Mi"},
                                        "limits": {"cpu": "1", "memory": "1Gi"},
                                    },
                                    "startupProbe": {
                                        "grpc": {"port": 9095},
                                        "periodSeconds": 2,
                                        "failureThreshold": 60,
                                    },
                                    "readinessProbe": {"grpc": {"port": 9095}, "periodSeconds": 5},
                                    "livenessProbe": {
                                        "grpc": {"port": 9095},
                                        "periodSeconds": 10,
                                        "failureThreshold": 3,
                                    },
                                }
                            ],
                            "volumes": volumes,
                        },
                    },
                },
            }
        )
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--banks", type=int, choices=[3, 5], default=3)
    parser.add_argument("--image", default="bank-fl:0.1.0")
    parser.add_argument("--host-data", default="/mnt/bank-fl")
    parser.add_argument("--output", type=Path, default=Path("k8s/deployment.yaml"))
    args = parser.parse_args()
    args.output.write_text(
        yaml.safe_dump_all(manifests(args.banks, args.image, args.host_data), sort_keys=False),
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
