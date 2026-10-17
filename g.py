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
NORMAL_SECONDS = 6.0
CLEANUP_SECONDS = 1.0
OUTPUT_LIMIT = 65536


def measure(case, argv, directory):
    """Run one fixed, targetless CLI and bound cleanup to its own Popen handle."""
    result = {
        "case": case, "status": "not_started", "elapsed_ms": 0,
        "elapsed_clamped": False, "returncode": None,
        "marker": False, "output_limit_exceeded": False,
        "cleanup": "not_needed", "direct_cli_exit_confirmed": False,
    }
    started = time.monotonic()
    child = None
    try:
        # Isolate user initialization and inherited Python/loader/agent variables.
        environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                       "HOME": str(directory), "TMPDIR": str(directory)}
        with tempfile.TemporaryFile(mode="w+b", dir=directory) as output:
            child = subprocess.Popen(
                argv, cwd=directory, env=environment,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
            )
            try:
                child.wait(timeout=NORMAL_SECONDS)
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
    return result


def main():
    report = {
        "schema": "targetless-lldb-startup-v1", "status": "unsupported_host",
        "cases": [], "debuggee_selected": False,
        "direct_cli_cleanup_complete": True,
        "all_descendants_exit_proven": False,
    }
    if platform.system() == "Darwin" and platform.machine() == "x86_64":
        with tempfile.TemporaryDirectory(prefix="lldb-cli-fixture-") as folder:
            directory = Path(folder)
            os.chmod(directory, 0o700)
            commands = directory / "fixed.lldb"
            module = directory / "hello.py"
            module.write_text("print('LLDB_HOST_PYTHON_FIXED_OK')\n", encoding="ascii")
            os.chmod(module, 0o600)
            commands.write_text("command script import hello.py\nquit\n", encoding="ascii")
            os.chmod(commands, 0o600)
            # First invocation measures initial embedded-Python startup in this job.
            # Second covers documented source-file routing; it is already warmed.
            # Version is deliberately last so it cannot warm the first measurement.
            cases = (
                ("script_batch_first", ["/usr/bin/xcrun", "lldb", "-x", "--no-use-colors", "--batch", "--source-quietly", "--one-line", "script print('LLDB_HOST_PYTHON_FIXED_OK')", "--one-line", "quit"]),
                ("script_source_second", ["/usr/bin/xcrun", "lldb", "-x", "--no-use-colors", "--source-quietly", "--source", str(commands)]),
                ("version_third", ["/usr/bin/xcrun", "lldb", "-x", "--no-use-colors", "--version"]),
            )
            report["status"] = "measurements_complete"
            for case, argv in cases:
                result = measure(case, argv, directory)
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
        print('{"schema":"targetless-lldb-startup-v1","status":"fixture_error"}')
        raise SystemExit(1)
