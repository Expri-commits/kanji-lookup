"""Actual helper processes must remain bounded before entering the shell."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "bounded-run.py"
_spec = importlib.util.spec_from_file_location("bounded_run", GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


class BoundedRunTests(unittest.TestCase):
    def run_code(self, code, timeout=2, limit=4096):
        return guard.run([sys.executable, "-c", code], timeout, limit)

    def test_success_preserves_utf8_stdout_stderr_and_exit_code(self):
        code, out, err = self.run_code("import os; os.write(1, '日本語'.encode()); os.write(2, b'warning'); raise SystemExit(7)")
        self.assertEqual((code, out, err), (7, "日本語".encode(), b"warning"))

    def test_exact_stdout_budget_succeeds(self):
        code, out, err = self.run_code("import os; os.write(1, b'x' * 4096)")
        self.assertEqual((code, len(out), err), (0, 4096, b""))

    def test_stdout_overflow_without_newlines_fails_without_partial_response(self):
        code, out, err = self.run_code("import os\nwhile True: os.write(1, b'x' * 65536)")
        self.assertEqual((code, out), (125, b""))
        self.assertIn(b"stdout limit exceeded", err)
        self.assertLessEqual(len(err), guard.STDERR_LIMIT)

    def test_one_byte_past_budget_is_rejected(self):
        code, out, err = self.run_code("import os; os.write(1, b'x' * 4097)")
        self.assertEqual((code, out), (125, b""))
        self.assertIn(b"stdout limit exceeded", err)

    def test_stderr_overflow_without_newlines_is_bounded(self):
        code, out, err = self.run_code("import os\nwhile True: os.write(2, b'x' * 65536)")
        self.assertEqual((code, out), (125, b""))
        self.assertIn(b"stderr limit exceeded", err.splitlines()[0])
        self.assertLessEqual(len(err), guard.STDERR_LIMIT)

    def test_timeout_kills_term_ignoring_process_and_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pids"
            script = ("import os, pathlib, signal, subprocess, sys, time; "
                      "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                      "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())+' '+str(child.pid)); "
                      "time.sleep(60)")
            start = time.monotonic()
            code, out, err = self.run_code(script, timeout=0.3)
            self.assertEqual((code, out), (124, b""))
            self.assertIn(b"timed out", err)
            self.assertLess(time.monotonic() - start, 2)
            self.assert_stopped(pidfile)

    def test_timeout_still_applies_after_output_pipes_close(self):
        code, _, err = self.run_code("import os, time; os.close(1); os.close(2); time.sleep(60)", timeout=0.2)
        self.assertEqual(code, 124)
        self.assertIn(b"timed out", err)

    def test_descendant_holding_pipes_cannot_outlive_exited_leader(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pids"
            script = ("import pathlib, subprocess, sys; "
                      "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))")
            code, _, err = self.run_code(script, timeout=0.3)
            self.assertEqual(code, 124)
            self.assertIn(b"timed out", err)
            self.assert_stopped(pidfile)

    def test_success_also_cleans_up_descendants_without_inherited_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pids"
            script = ("import pathlib, subprocess, sys; "
                      "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                      "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid))")
            self.assertEqual(self.run_code(script)[0], 0)
            self.assert_stopped(pidfile)

    def test_missing_executable_is_a_bounded_error(self):
        code, out, err = guard.run(["/nonexistent/kanji-helper"], 1, 4096)
        self.assertEqual((code, out), (126, b""))
        self.assertIn(b"cannot run helper", err)
        self.assertLessEqual(len(err), guard.STDERR_LIMIT)

    def test_cli_cancellation_kills_private_child_group(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pids"
            script = ("import os, pathlib, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)")
            proc = subprocess.Popen([sys.executable, str(GUARD), "ocr", sys.executable, "-c", script],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists(), "helper did not start")
                proc.terminate()
                out, err = proc.communicate(timeout=3)
                self.assertEqual((proc.returncode, out), (128 + signal.SIGTERM, b""))
                self.assertIn(b"cancelled", err)
                self.assert_stopped(pidfile)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.communicate(timeout=3)

    def assert_stopped(self, pidfile):
        pids = [int(pid) for pid in pidfile.read_text().split()]
        deadline = time.monotonic() + 1
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(any(alive(pid) for pid in pids), f"left a running child: {pids}")


@unittest.skipUnless(shutil.which("qs"), "Quickshell not installed")
class QuickshellCollectorTests(unittest.TestCase):
    def test_real_collectors_receive_only_bounded_output_and_deadline_errors(self):
        cases = {
            "success": "print('日本語')",
            "stdout": "import os\nwhile True: os.write(1, b'x'*65536)",
            "stderr": "import os\nwhile True: os.write(2, b'x'*65536)",
            "timeout": "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        }
        processes = []
        for name, code in cases.items():
            command = json.dumps([sys.executable, str(GUARD), "probe", sys.executable, "-c", code])
            processes.append(f'''Process {{
  running: true
  command: {command}
  stdout: StdioCollector {{ id: out_{name}; waitForEnd: true }}
  stderr: StdioCollector {{ id: err_{name}; waitForEnd: true }}
  onExited: function(code) {{
    console.log("BOUNDED_RESULT " + JSON.stringify({{
      name: "{name}", code: code, out: out_{name}.text, err: err_{name}.text
    }}))
    root.finished++
    if (root.finished === 4) Qt.quit()
  }}
}}''')
        qml = "import QtQuick\nimport Quickshell\nimport Quickshell.Io\nShellRoot {\nid: root\nproperty int finished: 0\n" + "\n".join(processes) + "\n}"
        with tempfile.TemporaryDirectory(prefix="kanji-qs-test-") as directory:
            path = Path(directory) / "shell.qml"
            path.write_text(qml)
            result = subprocess.run([shutil.which("qs"), "-p", str(path), "--no-color"],
                                    env=dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software"),
                                    capture_output=True, text=True, timeout=12)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        rows = [json.loads(line.split("BOUNDED_RESULT ", 1)[1])
                for line in output.splitlines() if "BOUNDED_RESULT " in line]
        results = {row["name"]: row for row in rows}
        self.assertEqual(set(results), set(cases), output)
        self.assertEqual((results["success"]["code"], results["success"]["out"]), (0, "日本語\n"))
        for name, code in [("stdout", 125), ("stderr", 125), ("timeout", 124)]:
            self.assertEqual(results[name]["code"], code)
            self.assertEqual(results[name]["out"], "")
            self.assertLessEqual(len(results[name]["err"].encode()), guard.STDERR_LIMIT)
        self.assertIn("timed out", results["timeout"]["err"])


if __name__ == "__main__":
    unittest.main()
