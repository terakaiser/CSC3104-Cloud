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

from app.bundle import stage_bundle
from app.data import replace_file, write_json
from app.resources import Sampler
from app.resources import summarize as summarize_resources

ROOT = Path(".demo")
CLUSTER = "bank-fl-demo"
IMAGE = "bank-fl:demo"
PORT = 19093
BANK_COUNTS = (3, 5)  # deployments the demo can set up
OUTAGE_SECONDS = 20.0  # how long a "temporary outage" keeps a bank offline


def dataset_name(synthetic, count=3, skew=1.0):
    """Folder under data/ for one bank count and skew, e.g. ulb, ulb-5, ulb-skew0."""
    name = "demo-synthetic" if synthetic else "ulb"
    if count != 3:
        name += f"-{count}"
    if skew != 1:
        name += f"-skew{skew:g}"
    return name


def banks():
    """How many banks the demo cluster was set up with (3 before this was configurable)."""
    try:
        return json.loads((ROOT / "settings.json").read_text(encoding="utf-8")).get("banks", 3)
    except (OSError, ValueError):
        return 3


def bank_ids(count=None):
    return tuple(f"bank-{i}" for i in range(1, (count or banks()) + 1))


def workloads(count=None):
    """Long-running demo pods. Finished CronJob pods are never Ready, so waits use these."""
    return ("coordinator", *bank_ids(count))


# A fault record is final once its replacement pod is Ready, timed out, or the kill failed.
FINAL_FAULT_STATES = {"ready", "timed_out", "failed"}


def fault_records(output: Path):
    """Every fault record of a run, oldest first. fault.json is the older single-fault name."""

    def number(path):
        _, _, suffix = path.stem.partition("-")
        return int(suffix) if suffix.isdigit() else 0

    return sorted(output.glob("fault*.json"), key=number)


def fault_finished(path: Path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False  # Missing or still being written.
    # Records written before fault tracking had no status and were always final.
    return record.get("status", "ready") in FINAL_FAULT_STATES


def add_parser(commands):
    parser = commands.add_parser("demo", help="prepare and present the Kubernetes demo")
    actions = parser.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("setup", help="prepare ULB data, image, and dedicated cluster")
    setup.add_argument("--synthetic", action="store_true", help="use software-test data")
    setup.add_argument(
        "--banks", type=int, choices=BANK_COUNTS, default=3, help="number of bank pods"
    )
    setup.add_argument(
        "--skew",
        type=float,
        default=1.0,
        help="how different the banks are: 0 identical, 1 standard, higher = less overlap",
    )
    start = actions.add_parser("start", help="train, stream progress, and export/evaluate results")
    start.add_argument("--rounds", type=int, default=30)
    start.add_argument("--deadline", type=float, default=30)
    start.add_argument("--mu", type=float, default=0.0, help="FedProx strength (0 = FedAvg)")
    fail = actions.add_parser("fail", help="fail one bank's pod during an active demo")
    fail.add_argument("--bank", default="bank-3")
    fail.add_argument(
        "--kind",
        choices=["kill", "absence"],
        default="kill",
        help="kill: delete the pod; absence: take the bank offline for --duration seconds",
    )
    fail.add_argument("--duration", type=float, default=OUTAGE_SECONDS)
    dashboard = actions.add_parser(
        "dashboard", help="open the local Kubernetes and training dashboard"
    )
    dashboard.add_argument("--port", type=int, default=8765)
    actions.add_parser("status", help="show demo pods")
    actions.add_parser("results", help="retry export and evaluation of the latest finished run")


def environment():
    return {
        **os.environ,
        "KUBECONFIG": str((ROOT / "kubeconfig").resolve()),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",  # Flower logs are read through a pipe.
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    }


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
    replace_file(temporary, target)


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


def setup(synthetic, count=3, skew=1.0):
    for executable in ("docker", "kubectl", "kind"):
        if not shutil.which(executable):
            raise ValueError(f"Install {executable} and add it to PATH before demo setup.")
    command("docker", "info", capture=True)
    ROOT.mkdir(exist_ok=True)
    # Each bank count and skew has its own prepared dataset, e.g. data/ulb, data/ulb-5.
    data = Path("data", dataset_name(synthetic, count, skew)).resolve()
    previous = read("settings.json") if (ROOT / "settings.json").exists() else None
    if previous and previous["synthetic"] != synthetic:
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
            prepare(data, rows=6000, banks=count, skew=skew)
        manifest = read_manifest(data)
        if (
            not manifest["synthetic"]
            or manifest["banks"] != count
            or manifest.get("skew", 1.0) != skew
        ):
            raise ValueError(f"{data} is not a {count}-bank synthetic dataset with skew {skew:g}.")
    else:
        setup_data(Path("data/raw"), data, banks=count, skew=skew)
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
        mounted = previous.get("mounted", previous["data"])
    else:
        mounted = str(data)
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
    save(
        "settings.json",
        {
            "data": str(data),
            "synthetic": synthetic,
            "banks": count,
            "skew": skew,
            "mounted": mounted,
        },
    )
    command("kind", "load", "docker-image", IMAGE, "--name", CLUSTER)
    if str(data) == mounted:
        host_data = "/mnt/bank-fl"
    else:
        # The node's data mount is fixed when the cluster is created. A different bank
        # count uses a different dataset, so copy it into the node instead of recreating
        # the cluster, which would discard the saved runs on its results volume.
        host_data = f"/mnt/{data.name}"
        node = f"{CLUSTER}-control-plane"
        command("docker", "exec", node, "rm", "-rf", host_data)
        command("docker", "cp", data, f"{node}:{host_data}")
        command("docker", "exec", node, "chmod", "-R", "a+rX", host_data)
    # Same generator as the checked-in k8s/deployment.yaml; only the image, bank count
    # and data path change for the demo.
    deployment = ROOT / "deployment.yaml"
    command(
        sys.executable,
        "k8s/render.py",
        *("--banks", count, "--image", IMAGE, "--host-data", host_data),
        *("--output", deployment),
        capture=True,
    )
    kubectl("apply", "-f", deployment)
    # Applying a smaller deployment does not remove a larger one's extra banks.
    extra = [f"bank-{i}" for i in range(count + 1, max(BANK_COUNTS) + 1)]
    if extra:
        kubectl("delete", "deployment", *extra, "--ignore-not-found")
    kubectl("rollout", "restart", "deployment")
    for name in workloads(count):
        kubectl("rollout", "status", f"deployment/{name}", "--timeout=180s")
    # metrics-server feeds per-pod CPU/memory to the dashboard and resources.csv. Training
    # does not depend on it, so a failed install (e.g. its image cannot be pulled) only warns.
    cluster = ("kubectl", "--context", f"kind-{CLUSTER}")
    try:
        command(*cluster, "apply", "-f", "k8s/metrics-server.yaml")
        command(
            *cluster,
            *("-n", "kube-system", "rollout", "status", "deployment/metrics-server"),
            "--timeout=180s",
        )
    except subprocess.CalledProcessError:
        print("Warning: metrics-server is not ready; pod CPU/memory will not be recorded.")
    print(f"Ready with {count} banks (skew {skew:g}). Run: uv run bank-fl demo start", flush=True)


def collect():
    state = read("latest.json")
    if not state.get("run_id"):
        raise ValueError("No finished run recorded. Inspect .demo/session.log before retrying.")
    directory = Path(state["output"]) / state["run_id"]
    directory.mkdir(parents=True, exist_ok=True)
    kubectl("cp", f"{state['pod']}:/results/{state['run_id']}/.", str(directory))
    from experiments.evaluate import evaluate
    from experiments.plot import plot_runs
    from experiments.recovery import summarize_all

    evaluate(directory, Path(read("settings.json")["data"]))
    plot_runs([directory], directory / "figures")
    faults = fault_records(Path(state["output"]))
    finished = [path for path in faults if fault_finished(path)]
    if len(finished) < len(faults):
        print(
            "Fault measurement is still pending. Run 'uv run bank-fl demo results' "
            "after the fail command finishes to include recovery measurements."
        )
    if finished:
        for number, recovery in enumerate(summarize_all(directory, finished)["faults"], 1):
            seconds = recovery["fault_to_accepted_update_seconds"]
            print(
                f"Failure {number}: {recovery['bank']} contributed again after {seconds:.1f}s."
                if seconds is not None
                else f"Failure {number}: {recovery['bank']} was not seen contributing again "
                "before training ended or its next failure."
            )
    samples = Path(state["output"]) / "resources.csv"
    usage = summarize_resources(samples) if samples.exists() else {}
    if usage:
        from experiments.plot import plot_resources

        shutil.copy(samples, directory / "resources.csv")
        write_json(directory / "resources.json", usage)
        plot_resources(directory, [json.loads(path.read_text()) for path in finished])
        for role, use in usage.items():
            print(
                f"{role}: CPU mean {use['cpu_millicores_mean']:.0f}m, "
                f"peak {use['cpu_millicores_peak']:.0f}m; "
                f"memory peak {use['memory_mib_peak']:.0f} MiB"
            )
    else:
        print("Pod CPU/memory were not recorded (is metrics-server running? Rerun demo setup).")
    summary = json.loads((directory / "summary.json").read_text())
    print(f"Result: {summary['status']} - {summary['committed_rounds']} committed rounds.")
    print(f"Results and charts: {directory}")
    if summary["status"] != "completed":
        raise ValueError("Training did not complete. Inspect the exported summary and event log.")


def start(rounds, deadline, mu=0.0):
    from app.config import RunConfig

    RunConfig(rounds=rounds, deadline=deadline, mu=mu)
    read("settings.json")
    if active():
        raise ValueError("A demo is already running.")
    # Reserve a non-default control port; never attach to an unrelated listener.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", PORT))
    count = banks()
    quorum = count // 2 + 1  # a majority: 2 of 3, 3 of 5
    kubectl(
        "wait",
        "--for=condition=Ready",
        "pod",
        "-l",
        f"app in ({','.join(workloads(count))})",
        "--timeout=120s",
    )
    pods = json.loads(kubectl("get", "pods", "-l", "app=coordinator", "-o", "json", capture=True))
    pod = pods["items"][0]["metadata"]["name"]
    output = Path("results/demo") / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    package = stage_bundle(output)
    save("latest.json", {"pod": pod, "output": str(output), "run_id": None})
    process = psutil.Process()
    active_started_at = time.time()
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
                f"{count} banks, quorum {quorum}. Wait for a few commits, then in another "
                "terminal run:\n"
                "  uv run bank-fl demo fail\n",
                flush=True,
            )
            save(
                "active.json",
                {
                    "pid": process.pid,
                    "created": process.create_time(),
                    "started_at": active_started_at,
                },
            )
            submission = subprocess.Popen(
                [
                    "flwr",
                    "run",
                    str(package),
                    "demo",
                    "--stream",
                    "--run-config",
                    f"rounds={rounds} deadline={deadline} mu={float(mu)} "
                    f'banks={count} quorum={quorum} label="demo"',
                ],
                env=environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            # Record each pod's CPU/memory for the whole run; collect() files it with the run.
            sampler = Sampler(lambda *args: kubectl(*args, capture=True), output / "resources.csv")
            with sampler, (ROOT / "session.log").open("w", encoding="utf-8") as session:
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


def fail(bank, kind="kill", duration=OUTAGE_SECONDS):
    if bank not in bank_ids():
        raise ValueError(f"bank must be one of: {', '.join(bank_ids())}")
    if kind not in ("kill", "absence"):
        raise ValueError("kind must be kill or absence")
    if not active():
        raise ValueError("Start the demo and wait for training commits before triggering a fault.")
    state = read("latest.json")
    output = Path(state["output"])
    records = fault_records(output)
    # Any number of kills per run, but one at a time, so each recovery time belongs to
    # exactly one kill.
    if records and not fault_finished(records[-1]):
        raise ValueError("Wait for the previous bank pod's replacement to become Ready first.")
    record = output / f"fault-{len(records) + 1}.json"
    try:
        # Reserve the number atomically, so two simultaneous kills cannot share a record.
        with record.open("x", encoding="utf-8") as stream:
            json.dump({"bank": bank, "unix_time": time.time(), "status": "starting"}, stream)
    except FileExistsError as exc:
        raise ValueError("Another bank failure is being injected right now.") from exc
    print(
        f"Terminating {bank}'s pod. The other banks can keep training."
        if kind == "kill"
        else f"Taking {bank} offline for {duration:g} s. The other banks can keep training.",
        flush=True,
    )
    try:
        command(
            sys.executable,
            "-m",
            "experiments.fault",
            *("--kind", kind, "--duration", duration),
            "--bank",
            bank,
            "--output",
            record,
        )
    except BaseException as exc:
        # The injector can fail before writing its own record; never leave the run blocked,
        # and keep the reason so the dashboard can show more than "unknown error".
        if not fault_finished(record):
            record.write_text(
                json.dumps(
                    {
                        "bank": bank,
                        "unix_time": time.time(),
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}. "
                        "See the dashboard's terminal for the injector's output.",
                    }
                ),
                encoding="utf-8",
            )
        raise
    print("Pod replacement check finished. Watch training for the bank's accepted update.")
    return record


def dispatch(args):
    if not Path("k8s/deployment.yaml").exists():
        raise ValueError("Run demo commands from the repository root.")
    try:
        if args.action == "setup":
            if active():
                raise ValueError("Wait for the active demo to finish before setup.")
            setup(args.synthetic, args.banks, args.skew)
        elif args.action == "start":
            start(args.rounds, args.deadline, args.mu)
        elif args.action == "fail":
            fail(args.bank, args.kind, args.duration)
        elif args.action == "results":
            if active():
                raise ValueError("Wait for training to finish before collecting results.")
            collect()
        elif args.action == "dashboard":
            from app.dashboard import serve

            serve(args.port)
        else:
            read("settings.json")
            kubectl("get", "pods")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Demo command failed: {exc}") from exc
