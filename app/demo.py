"""A guided Kubernetes demonstration using a dedicated kind cluster."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import yaml

ROOT = Path(".demo")
CLUSTER = "bank-fl-demo"
IMAGE = "bank-fl:demo"
PORT = 19093


def add_parser(commands):
    parser = commands.add_parser("demo", help="prepare and present the Kubernetes demo")
    actions = parser.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("setup", help="prepare ULB data, image, and dedicated cluster")
    setup.add_argument("--synthetic", action="store_true", help="use software-test data")
    start = actions.add_parser("start", help="train, stream progress, and export/evaluate results")
    start.add_argument("--rounds", type=int, default=30)
    start.add_argument("--deadline", type=float, default=30)
    fail = actions.add_parser("fail", help="replace bank 3's pod during an active demo")
    fail.add_argument("--bank", choices=["bank-1", "bank-2", "bank-3"], default="bank-3")
    actions.add_parser("status", help="show demo pods")
    actions.add_parser("results", help="retry export and evaluation of the latest finished run")


def environment():
    return {
        **os.environ,
        "KUBECONFIG": str((ROOT / "kubeconfig").resolve()),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    }


def stage_bundle(output):
    package = output / "package"
    package.mkdir()
    shutil.copy("pyproject.toml", package)
    (package / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for name in ("app", "experiments"):
        shutil.copytree(name, package / name, ignore=shutil.ignore_patterns("__pycache__"))
    return package


def command(*args, capture=False):
    result = subprocess.run(
        [str(arg) for arg in args],
        check=True,
        env=environment(),
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else None


def kubectl(*args, capture=False):
    return command(
        "kubectl", "--context", f"kind-{CLUSTER}", "-n", "bank-fl", *args, capture=capture
    )


def save(name, value):
    target = ROOT / name
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(target)


def read(name):
    path = ROOT / name
    if not path.exists():
        raise ValueError("Demo is not prepared. Run: uv run bank-fl demo setup")
    return json.loads(path.read_text(encoding="utf-8"))


def active():
    path = ROOT / "active.json"
    if not path.exists():
        return False
    state = read("active.json")
    try:
        return psutil.Process(state["pid"]).create_time() == state["created"]
    except psutil.NoSuchProcess:
        return False


def setup(synthetic):
    for executable in ("docker", "kubectl", "kind"):
        if not shutil.which(executable):
            raise ValueError(f"Install {executable} and add it to PATH before demo setup.")
    command("docker", "info", capture=True)
    ROOT.mkdir(exist_ok=True)
    data = Path("data/demo-synthetic" if synthetic else "data/ulb").resolve()
    if (ROOT / "settings.json").exists() and read("settings.json")["data"] != str(data):
        raise ValueError(
            "This demo is configured for another dataset; use its original setup mode."
        )
    from app.data import prepare, read_manifest
    from app.download import setup_data

    print(
        "Preparing synthetic software-test data." if synthetic else "Preparing real ULB data.",
        flush=True,
    )
    if synthetic:
        if not (data / "manifest.json").exists():
            prepare(data, rows=6000)
        manifest = read_manifest(data)
        if not manifest["synthetic"] or manifest["banks"] != 3:
            raise ValueError("Demo synthetic dataset must contain three synthetic banks.")
    else:
        setup_data(Path("data/raw"), data)
    print("Building the training image. First setup can take several minutes.", flush=True)
    command("docker", "build", "-t", IMAGE, ".")
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [
            {
                "role": "control-plane",
                "extraMounts": [
                    {
                        "hostPath": str(data),
                        "containerPath": "/mnt/bank-fl",
                        "readOnly": True,
                    }
                ],
            }
        ],
    }
    config_path = ROOT / "kind.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    clusters = command("kind", "get", "clusters", capture=True).splitlines()
    if CLUSTER in clusters:
        if not (ROOT / "settings.json").exists():
            raise ValueError(f"Cluster {CLUSTER} already exists without demo ownership records.")
        command(
            "kind", "export", "kubeconfig", "--name", CLUSTER, "--kubeconfig", ROOT / "kubeconfig"
        )
    else:
        command(
            "kind",
            "create",
            "cluster",
            "--name",
            CLUSTER,
            "--config",
            config_path,
            "--kubeconfig",
            ROOT / "kubeconfig",
            "--wait",
            "120s",
        )
    save("settings.json", {"data": str(data), "synthetic": synthetic})
    command("kind", "load", "docker-image", IMAGE, "--name", CLUSTER)
    # Use the checked-in deployment; only the image changes for the demo.
    documents = list(yaml.safe_load_all(Path("k8s/deployment.yaml").read_text()))
    for document in documents:
        if document["kind"] == "Deployment":
            document["spec"]["template"]["spec"]["containers"][0]["image"] = IMAGE
    deployment = ROOT / "deployment.yaml"
    deployment.write_text(yaml.safe_dump_all(documents), encoding="utf-8")
    kubectl("apply", "-f", deployment)
    kubectl("rollout", "restart", "deployment")
    for name in ("coordinator", "bank-1", "bank-2", "bank-3"):
        kubectl("rollout", "status", f"deployment/{name}", "--timeout=180s")
    print("Ready. Run: uv run bank-fl demo start", flush=True)


def collect():
    state = read("latest.json")
    if not state.get("run_id"):
        raise ValueError("No finished run recorded. Inspect .demo/session.log before retrying.")
    directory = Path(state["output"]) / state["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    kubectl("cp", f"{state['pod']}:/results/{state['run_id']}/.", str(directory))
    from experiments.evaluate import evaluate
    from experiments.plot import plot_runs
    from experiments.recovery import summarize

    evaluate(directory, Path(read("settings.json")["data"]))
    plot_runs([directory], directory / "figures")
    fault = Path(state["output"]) / "fault.json"
    if (fault.parent / "fault-requested").exists() and not fault.exists():
        print(
            "Fault measurement is still pending. Run 'uv run bank-fl demo results' "
            "after the fail command finishes to include recovery measurements."
        )
    if fault.exists():
        recovery = summarize(directory, fault)
        seconds = recovery["fault_to_accepted_update_seconds"]
        print(
            f"Bank contributed again after {seconds:.1f}s."
            if seconds is not None
            else "Bank contribution after replacement was not observed; repeat with more rounds."
        )
    summary = json.loads((directory / "summary.json").read_text())
    print(f"Result: {summary['status']} - {summary['committed_rounds']} committed rounds.")
    print(f"Results and charts: {directory}")
    if summary["status"] != "completed":
        raise ValueError("Training did not complete. Inspect the exported summary and event log.")


def start(rounds, deadline):
    from app.config import RunConfig

    RunConfig(rounds=rounds, deadline=deadline)
    read("settings.json")
    if active():
        raise ValueError("A demo is already running.")
    # Reserve a non-default control port; never attach to an unrelated listener.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", PORT))
    kubectl("wait", "--for=condition=Ready", "pod", "--all", "--timeout=120s")
    pods = json.loads(kubectl("get", "pods", "-l", "app=coordinator", "-o", "json", capture=True))
    pod = pods["items"][0]["metadata"]["name"]
    output = Path("results/demo") / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    package = stage_bundle(output)
    save("latest.json", {"pod": pod, "output": str(output), "run_id": None})
    process = psutil.Process()
    forward = submission = None
    try:
        with (ROOT / "forward.log").open("w") as log:
            forward = subprocess.Popen(
                [
                    "kubectl",
                    "--context",
                    f"kind-{CLUSTER}",
                    "-n",
                    "bank-fl",
                    "port-forward",
                    "service/coordinator",
                    f"{PORT}:9093",
                    "--address",
                    "127.0.0.1",
                ],
                env=environment(),
                stdout=log,
                stderr=log,
            )
            until = time.monotonic() + 20
            while True:
                if forward.poll() is not None or time.monotonic() > until:
                    raise ValueError("Port forwarding failed. See .demo/forward.log.")
                try:
                    with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.2)
            print(
                "Three banks, quorum 2. Wait for a few commits, then in another terminal run:\n"
                "  uv run bank-fl demo fail\n",
                flush=True,
            )
            submission = subprocess.Popen(
                [
                    "flwr",
                    "run",
                    str(package),
                    "demo",
                    "--stream",
                    "--run-config",
                    f'rounds={rounds} deadline={deadline} label="demo"',
                ],
                env=environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            save("active.json", {"pid": process.pid, "created": process.create_time()})
            with (ROOT / "session.log").open("w", encoding="utf-8") as session:
                for line in submission.stdout:
                    print(line, end="", flush=True)
                    session.write(line)
                    session.flush()
                    match = re.search(r"Results saved to /results/([\w-]+)", line)
                    if match:
                        save("latest.json", {"pod": pod, "output": str(output), "run_id": match[1]})
            if submission.wait():
                raise ValueError("Flower submission failed. See .demo/session.log.")
    finally:
        (ROOT / "active.json").unlink(missing_ok=True)
        for child in (submission, forward):
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
    collect()


def fail(bank):
    if not active():
        raise ValueError("Start the demo and wait for training commits before triggering a fault.")
    state = read("latest.json")
    output = Path(state["output"])
    # One deliberate fault per run keeps recovery attribution unambiguous.
    with (output / "fault-requested").open("x"):
        pass
    print(f"Terminating {bank}'s pod. The remaining two banks can keep training.", flush=True)
    command(
        sys.executable,
        "-m",
        "experiments.fault",
        "--kind",
        "kill",
        "--bank",
        bank,
        "--output",
        output / "fault.json",
    )
    print("Pod replacement check finished. Watch training for the bank's accepted update.")


def dispatch(args):
    if not Path("k8s/deployment.yaml").exists():
        raise ValueError("Run demo commands from the repository root.")
    try:
        if args.action == "setup":
            if active():
                raise ValueError("Wait for the active demo to finish before setup.")
            setup(args.synthetic)
        elif args.action == "start":
            start(args.rounds, args.deadline)
        elif args.action == "fail":
            fail(args.bank)
        elif args.action == "results":
            if active():
                raise ValueError("Wait for training to finish before collecting results.")
            collect()
        else:
            read("settings.json")
            kubectl("get", "pods")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Demo command failed: {exc}") from exc
