"""Fresh targetless LLDB CLI fixture; no application or debuggee is selected.

CLI provenance: https://lldb.llvm.org/man/lldb.html
Host Python: https://lldb.llvm.org/use/tutorials/python-embedded-interpreter.html
Module import: https://lldb.llvm.org/use/tutorials/writing-custom-commands.html
Only closed measurements are exported. Transient tool output is never published.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


MARKER = b"LLDB_HOST_PYTHON_FIXED_OK"
BASELINE_SECONDS = 6.0
SDK_SECONDS = 30.0
CLEANUP_SECONDS = 1.0
OUTPUT_LIMIT = 65536


def measure(case, argv, directory, child_home, normal_seconds):
    """Run one fixed, targetless CLI and bound cleanup to its own Popen handle."""
    result = {
        "case": case, "status": "not_started", "elapsed_ms": 0,
        "elapsed_clamped": False, "returncode": None,
        "marker": False, "output_limit_exceeded": False,
        "cleanup": "not_needed", "direct_cli_exit_confirmed": False,
        "normal_budget_seconds": int(normal_seconds),
        "cleanup_budget_seconds": int(CLEANUP_SECONDS),
        "completed_within_baseline_6s": False,
    }
    started = time.monotonic()
    child = None
    try:
        # Isolate user initialization and inherited Python/loader/agent variables.
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                       "HOME": child_home, "TMPDIR": str(directory)}
        with tempfile.TemporaryFile(mode="w+b", dir=directory) as output:
            child = subprocess.Popen(
                argv, cwd=directory, env=environment,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
            )
            try:
                child.wait(timeout=normal_seconds)
                result["status"] = "completed"
            except subprocess.TimeoutExpired:
                result["status"] = "normal_budget_exceeded"
                # No debuggee exists. Signal only this retained, owned CLI handle.
                deadline = time.monotonic() + CLEANUP_SECONDS
                result["cleanup"] = "unconfirmed"
                try:
                    child.terminate()
                    child.wait(timeout=max(0.0, min(0.5, deadline - time.monotonic())))
                    result["cleanup"] = "terminated_direct_cli"
                except subprocess.TimeoutExpired:
                    try:
                        child.kill()
                        child.wait(timeout=max(0.0, deadline - time.monotonic()))
                        result["cleanup"] = "killed_direct_cli"
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                except OSError:
                    pass
            result["direct_cli_exit_confirmed"] = child.poll() is not None
            code = child.returncode
            result["returncode"] = code if type(code) is int and -255 <= code <= 255 else None
            if result["direct_cli_exit_confirmed"]:
                output.seek(0)
                data = output.read(OUTPUT_LIMIT + 1)
                result["output_limit_exceeded"] = len(data) > OUTPUT_LIMIT
                # Exact line prevents the echoed command text from being a marker.
                result["marker"] = not result["output_limit_exceeded"] and MARKER in data.splitlines()
    except OSError:
        result["status"] = "os_error"
        if child is not None:
            result["direct_cli_exit_confirmed"] = child.poll() is not None
            if not result["direct_cli_exit_confirmed"]:
                result["cleanup"] = "unconfirmed"
    finally:
        elapsed = max(0, int((time.monotonic() - started) * 1000))
        result["elapsed_ms"] = min(elapsed, 60000)
        result["elapsed_clamped"] = elapsed > 60000
        result["completed_within_baseline_6s"] = (
            result["status"] == "completed" and elapsed <= int(BASELINE_SECONDS * 1000)
        )
    return result


def main():
    report = {
        "schema": "targetless-lldb-startup-v2", "status": "unsupported_host",
        "cases": [], "debuggee_selected": False,
        "direct_cli_cleanup_complete": True,
        "all_descendants_exit_proven": False,
    }
    supported = platform.system() == "Darwin" and platform.machine() == "x86_64"
    runner_home = os.environ.get("HOME", "")
    if supported and (not runner_home or not Path(runner_home).is_absolute() or not Path(runner_home).is_dir()):
        report["status"] = "runner_home_unavailable"
    elif supported:
        with tempfile.TemporaryDirectory(prefix="lldb-cli-fixture-") as folder:
            directory = Path(folder)
            os.chmod(directory, 0o700)
            commands = directory / "fixed.lldb"
            module = directory / "hello.py"
            module.write_text("print('LLDB_HOST_PYTHON_FIXED_OK')\n", encoding="ascii")
            os.chmod(module, 0o600)
            commands.write_text("command script import hello.py\nquit\n", encoding="ascii")
            os.chmod(commands, 0o600)
            # The two SDK-only source cases share argv, cwd, TMPDIR and PATH.
            # Only their child HOME values differ; global HOME is never changed.
            # Fixed order can warm caches, so timing does not isolate HOME causality.
            source_argv = ["/usr/bin/xcrun", "lldb", "-x", "--no-use-colors", "--source-quietly", "--source", str(commands)]
            cases = (
                ("source_private_home_first", source_argv, str(directory), SDK_SECONDS),
                ("source_runner_home_second", source_argv, runner_home, SDK_SECONDS),
                ("version_third", ["/usr/bin/xcrun", "lldb", "-x", "--no-use-colors", "--version"], str(directory), BASELINE_SECONDS),
            )
            report["status"] = "measurements_complete"
            for case, argv, child_home, normal_seconds in cases:
                result = measure(case, argv, directory, child_home, normal_seconds)
                report["cases"].append(result)
                if not result["direct_cli_exit_confirmed"]:
                    report["status"] = "owned_cli_lifetime_unknown_no_more_invocations"
                    report["direct_cli_cleanup_complete"] = False
                    break
    # Fixed artifact only; never echo raw CLI output, exceptions or environment.
    with Path("0.json").open("x", encoding="ascii") as sink:
        json.dump(report, sink, separators=(",", ":"), ensure_ascii=True)
        sink.write("\n")
    return 0 if report["status"] == "measurements_complete" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print('{"schema":"targetless-lldb-startup-v2","status":"fixture_error"}')
        raise SystemExit(1)
