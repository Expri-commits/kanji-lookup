"""OCR launcher regressions and recognition of small outlined subtitles."""

import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import unittest


OCR_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ocr.sh"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ocr"


class OcrLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin_dir = Path(self.tmp.name)
        self.env = dict(os.environ, PATH=f"{self.bin_dir}:{os.environ['PATH']}")
        self.env["TMPDIR"] = self.tmp.name
        self.env.pop("KANJI_LOOKUP_OCR_LANGS", None)
        self.stub("tesseract", '''
if [[ $1 == --list-langs ]]; then
  printf 'jpn\njpn_vert\n'
else
  cat >/dev/null
  if [[ $1 == */subtitle.png ]]; then
    printf '%s\\n' "${PREPARED_TEXT:-愛}" > "$2.txt"
    score=${PREPARED_SCORE:-96}
  else
    printf ' 日本語  を勉強しています\\n' > "$2.txt"
    score=${RAW_SCORE:-95}
  fi
  printf '5\\t1\\t1\\t1\\t1\\t1\\t0\\t0\\t20\\t20\\t%s\\ttext\\n' "$score" > "$2.tsv"
fi
''')
        self.stub("grim", '''
[[ $1 == -g && $2 == '10,20 300x80' ]] || exit 1
printf 'image bytes' > "$3"
''')
        self.stub("magick", '''
if [[ $1 == identify ]]; then
  printf '30 30'
else
  printf 'prepared image' > "${@: -1}"
  printf '1'
fi
''')

    def stub(self, name, body):
        path = self.bin_dir / name
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_ocr(self, *args):
        with subprocess.Popen(
            ["bash", str(OCR_SCRIPT), *args],
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as proc:
            try:
                # Keep stdin open: communicate() would close it and hide the bug.
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                self.fail("OCR blocked on the launcher's open stdin pipe")
            result = proc.returncode, proc.stdout.read(), proc.stderr.read()
        self.assertEqual(list(self.bin_dir.glob("kanji-lookup-ocr.*")), [])
        return result

    def test_cancel_with_open_launcher_stdin(self):
        # Like slurp, read rectangle suggestions until EOF before accepting input.
        self.stub("slurp", "cat >/dev/null\nexit 1\n")
        self.assertEqual(self.run_ocr(), (0, "", ""))

    def test_selection_with_open_launcher_stdin(self):
        self.stub("slurp", "cat >/dev/null\nprintf '10,20 300x80\\n'\n")
        self.assertEqual(self.run_ocr(), (0, "日本語 を勉強しています\n", ""))

    def test_better_prepared_result_replaces_incorrect_raw_result(self):
        self.env["RAW_SCORE"] = "60"
        self.assertEqual(self.run_ocr("--file", "input.png"), (0, "愛\n", ""))

    def test_lower_confidence_preparation_keeps_original_result(self):
        self.env.update(RAW_SCORE="80", PREPARED_SCORE="30")
        self.assertEqual(self.run_ocr("--file", "input.png"),
                         (0, "日本語 を勉強しています\n", ""))

    def test_preprocessing_failure_keeps_original_result(self):
        self.env["RAW_SCORE"] = "80"
        self.stub("magick", "exit 1\n")
        self.assertEqual(self.run_ocr("--file", "input.png"),
                         (0, "日本語 を勉強しています\n", ""))

    def test_confident_raw_result_does_not_run_preprocessing(self):
        self.stub("magick", 'touch "$TMPDIR/unexpected-preprocessing"\nexit 1\n')
        self.run_ocr("--file", "input.png")
        self.assertFalse((self.bin_dir / "unexpected-preprocessing").exists())

    def test_capture_failure_cleans_temporary_files(self):
        self.stub("slurp", "printf '10,20 300x80\\n'\n")
        self.stub("grim", "exit 1\n")
        self.assertEqual(self.run_ocr(), (1, "", ""))

    def test_zero_confidence_is_not_returned_as_text(self):
        self.env.update(RAW_SCORE="0", PREPARED_SCORE="0")
        self.assertEqual(self.run_ocr("--file", "input.png"),
                         (1, "", "no text recognized\n"))


class OcrRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(shutil.which(cmd) for cmd in ("magick", "tesseract")):
            raise unittest.SkipTest("uses existing ImageMagick and Tesseract; installs nothing")
        langs = subprocess.run(["tesseract", "--list-langs"],
                               capture_output=True, text=True, check=True).stdout.splitlines()
        if "jpn" not in langs:
            raise unittest.SkipTest("Japanese Tesseract data is not installed")

    def setUp(self):
        self.env = dict(os.environ, KANJI_LOOKUP_OCR_LANGS="jpn")

    def recognize(self, image):
        return subprocess.run(["bash", str(OCR_SCRIPT), "--file", str(image)],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_screenshot_crops(self):
        expected = {
            "love": "愛", "love-tight": "愛", "time": "時",
            "place": "場所", "work": "作品", "talk": "語",
            "line": "時と場所をわきまえず", "dark-background": "晩",
        }
        for name, text in expected.items():
            with self.subTest(crop=name):
                result = self.recognize(FIXTURES / f"{name}.png")
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr),
                                 (0, text, ""))

    def test_scenery_without_text(self):
        result = self.recognize(FIXTURES / "blank.png")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, "", "no text recognized\n"))

    def test_capture_uses_the_same_recognition_as_file_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            stub_dir = Path(directory)
            for name, body in {
                "slurp": "cat >/dev/null\nprintf '10,20 29x35\\n'\n",
                "grim": 'cp -- "$OCR_FIXTURE" "$3"\n',
            }.items():
                stub = stub_dir / name
                stub.write_text("#!/bin/bash\nset -eu\n" + body)
                stub.chmod(0o755)
            env = dict(self.env, PATH=f"{stub_dir}:{os.environ['PATH']}",
                       TMPDIR=directory, OCR_FIXTURE=str(FIXTURES / "love.png"))
            result = subprocess.run(["bash", str(OCR_SCRIPT)], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "愛\n", ""))
            self.assertEqual(list(stub_dir.glob("kanji-lookup-ocr.*")), [])


if __name__ == "__main__":
    unittest.main()
