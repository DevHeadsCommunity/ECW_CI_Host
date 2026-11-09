"""Offline API stand-ins only. These tests never contact ECW or a board."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from ecw_ci_host import ECWClient, ECWError, RunConfig, run_test
from ecw_ci_host import cli, hil
from ecw_ci_host.booking import timestamp
from ecw_ci_host.jobs import load_specs, read_member, verify_checks

ROOT = Path(__file__).resolve().parents[1]


class FakeECW:
    def __init__(self):
        self.events = []
        self.filename = None
        self.payload = None
        self.job_status = "succeeded"
        self.fail_upload = self.fail_flash = self.fail_download = self.fail_release = False
        self.missing_manifest = self.wrong_metadata = self.short = self.expired = False
        self.bad_hil_prepare = False
        self.existing = []
        self.selected = []
        self.hil_writes = []
        self.board_name = "Arduino UNO R4 WiFi"
        self.log = "\n".join(f"ECW_CI_HOST_SAMPLE {i} LED=ON" for i in range(2, 7))

    def redact(self, value):
        return value.replace("offline-secret", "[redacted]")

    def upload(self, booking_id, content, filename):
        self.events.append(("POST", "/upload"))
        self.filename = filename
        self.content = content
        return {"status": "failed" if self.fail_upload else "okay"}

    def request(self, path, *, method="GET", params=None, body=None, **kwargs):
        self.events.append((method, path))
        now = datetime.now(timezone.utc)
        if path == "/board_types":
            return [{"id": 10, "board_name": "Arduino UNO R4 WiFi"}]
        if path == "/bookings/me":
            return self.existing
        if path == "/auto-bookings":
            return {"id": 99}
        if path == "/booking":
            end = now + timedelta(minutes=30)
            if self.short:
                end = now + timedelta(minutes=2)
            if self.expired:
                end = now - timedelta(seconds=1)
            return {"id": 99, "board_id": 12, "board_name": None,
                    "status": "confirmed" if self.short or self.expired else "active",
                    "start_utc": (now - timedelta(minutes=1)).isoformat(), "end_utc": end.isoformat()}
        if path == "/board":
            return {"id": 12, "board_type_id": 10}
        if path == "/board_type":
            return {"id": 10, "board_name": self.board_name, "is_mcu": True}
        if path == "/extend_booking":
            self.short = False
            return {"id": 99}
        if path == "/cancel-booking":
            if self.fail_release:
                raise ECWError("Release failed: offline-secret")
            return {"status": "okay"}
        if path == "/v1/artifacts/my-uploads":
            if method == "POST":
                assert params["code"] == self.filename
                return {"status": "failed" if self.fail_flash else "okay"}
            return {"items": [] if self.missing_manifest else [{"filename": self.filename}]}
        if path == "/v1/peripherals-list":
            return [{"id": 7, "name": "BME280"}]
        if path == "/v1/peripherals":
            if method == "PUT":
                self.selected = [{"id": 7, "configuration_id": 850}]
                return {"status": "okay"}
            return self.selected
        if path == "/v1/peripheral-prepare":
            return {"status": "failed" if self.bad_hil_prepare else "okay"}
        if path == "/v1/peripheral-program-value":
            self.hil_writes.append((params, body))
            return {"status": "okay"}
        if path == "/v1/ci/jobs":
            self.payload = body
            return {"id": 101, "status": "queued"}
        if path.endswith("/results"):
            return {"status": self.job_status, "results": {c["id"]: {"success": self.job_status == "succeeded"}
                                                           for c in self.payload["commands"]}}
        if path.endswith("/logs"):
            return {"logs": [] if params["cursor"] else ["Job started"], "next_cursor": 1}
        if path == "/v1/ci/jobs/101":
            return {"id": 101, "status": self.job_status,
                    "metadata": {} if self.wrong_metadata else self.payload["metadata"]}
        if path == "/v1/ci/jobs/101/cancel" and method == "POST":
            assert self.job_status == "queued"
            self.job_status = "cancelled"
            return {"id": 101, "status": "cancelled"}
        raise AssertionError(f"Unexpected offline API request: {method} {path}")

    def download(self, path, destination):
        self.events.append(("GET", path))
        if self.fail_download:
            raise ECWError("Artifact transfer failed")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as bundle:
            bundle.writestr("logs/arduino.log", self.log)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        firmware = self.root / "firmware with unsafe-name.bin"
        firmware.write_bytes(b"real-firmware-placeholder-for-offline-tests")
        self.config = RunConfig(board="Arduino UNO R4 WiFi", firmware=firmware,
                                jobs_dir=ROOT / "examples/arduino/jobs", output_dir=self.root / "artifacts",
                                poll_interval=0.001)
        self.api = FakeECW()

    def run_config(self, **kwargs):
        return run_test(replace(self.config, **kwargs), client=self.api)

    def test_complete_run_passes_without_github_environment_files(self):
        with patch.dict("os.environ", {}, clear=True):
            result = self.run_config()
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.jobs[0]["checks"][0]["samples"], 5)
        self.assertLess(self.api.events.index(("POST", "/upload")), self.api.events.index(("POST", "/v1/artifacts/my-uploads")))
        self.assertLess(self.api.events.index(("POST", "/v1/artifacts/my-uploads")), self.api.events.index(("POST", "/v1/ci/jobs")))
        self.assertEqual(self.api.events[-1], ("GET", "/cancel-booking"))
        self.assertEqual(self.api.content, self.config.firmware.read_bytes())
        self.assertRegex(self.api.filename, r"^[A-Za-z0-9._]{1,64}$")
        summary = json.loads((Path(result.output_dir) / "summary.json").read_text())
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(self.api.payload["metadata"]["run_id"], result.run_id)

    def test_every_run_has_unique_output_and_idempotency_key(self):
        first = self.run_config()
        key = self.api.payload["request_id"]
        second = self.run_config()
        self.assertNotEqual(first.output_dir, second.output_dir)
        self.assertNotEqual(key, self.api.payload["request_id"])

    def test_existing_booking_is_reused_and_preserved(self):
        self.api.existing = [{"id": 99, "board_name": self.config.board}]
        result = self.run_config()
        self.assertTrue(result.success, result.errors)
        self.assertFalse(result.booking_created)
        self.assertNotIn(("POST", "/auto-bookings"), self.api.events)
        self.assertNotIn(("GET", "/cancel-booking"), self.api.events)

    def test_new_booking_option_skips_existing_booking(self):
        self.api.existing = [{"id": 98, "board_name": self.config.board}]
        result = self.run_config(reuse_existing=False)
        self.assertTrue(result.success, result.errors)
        self.assertTrue(result.booking_created)
        self.assertNotIn(("GET", "/bookings/me"), self.api.events)

    def test_caller_booking_is_preserved_on_failure(self):
        self.api.job_status = "failed"
        result = self.run_config(booking_id=99)
        self.assertFalse(result.success)
        self.assertNotIn(("POST", "/auto-bookings"), self.api.events)
        self.assertNotIn(("GET", "/cancel-booking"), self.api.events)
        self.assertTrue((Path(result.output_dir) / "jobs/serial/artifacts.zip").exists())
        self.assertTrue((Path(result.output_dir) / "jobs/serial/results.json").exists())

    def test_upload_and_manifest_failures_never_flash(self):
        for flag in ("fail_upload", "missing_manifest"):
            with self.subTest(flag=flag):
                self.api = FakeECW()
                setattr(self.api, flag, True)
                result = self.run_config()
                self.assertFalse(result.success)
                self.assertNotIn(("POST", "/v1/artifacts/my-uploads"), self.api.events)
                self.assertIn(("GET", "/cancel-booking"), self.api.events)

    def test_failed_flash_never_creates_jobs(self):
        self.api.fail_flash = True
        result = self.run_config()
        self.assertFalse(result.success)
        self.assertNotIn(("POST", "/v1/ci/jobs"), self.api.events)
        self.assertEqual(self.api.events.count(("POST", "/v1/artifacts/my-uploads")), 1)

    def test_missing_artifacts_or_metadata_cannot_pass(self):
        for flag in ("fail_download", "wrong_metadata"):
            with self.subTest(flag=flag):
                self.api = FakeECW()
                setattr(self.api, flag, True)
                self.assertFalse(self.run_config().success)

    def test_successful_capture_with_broken_firmware_sequence_fails(self):
        self.api.log = "\n".join(f"ECW_CI_HOST_SAMPLE {i} LED=ON" for i in (1, 2, 4, 5, 6))
        result = self.run_config()
        self.assertFalse(result.success)
        checks = json.loads((Path(result.output_dir) / "jobs/serial/checks.json").read_text())
        self.assertFalse(checks["passed"])

    def test_release_failure_is_reported_and_secret_is_redacted(self):
        self.api.fail_release = True
        result = self.run_config()
        self.assertFalse(result.success)
        text = (Path(result.output_dir) / "summary.json").read_text()
        self.assertNotIn("offline-secret", text)
        self.assertIn("[redacted]", text)

    def test_wrong_board_metadata_stops_before_upload(self):
        self.api.board_name = "Another board"
        self.assertFalse(self.run_config().success)
        self.assertNotIn(("POST", "/upload"), self.api.events)

    def test_short_created_booking_is_extended_once(self):
        self.api.short = True
        self.assertTrue(self.run_config().success)
        self.assertEqual(self.api.events.count(("POST", "/extend_booking")), 1)

    def test_short_supplied_booking_is_not_modified(self):
        self.api.short = True
        self.assertFalse(self.run_config(booking_id=99).success)
        self.assertNotIn(("POST", "/extend_booking"), self.api.events)
        self.assertNotIn(("GET", "/cancel-booking"), self.api.events)

    def test_expired_confirmed_booking_stops_without_poll_sleep(self):
        self.api.expired = True
        with patch("ecw_ci_host.wait_for_booking.time.sleep") as sleep:
            result = self.run_config()
        self.assertFalse(result.success)
        sleep.assert_not_called()

    def test_hil_is_prepared_before_data_and_firmware(self):
        csv = self.root / "sensor.csv"
        csv.write_text("Temperature (°C),Humidity (%RH),Pressure (hPa)\n25,50,1013\n26,51,1014\n")
        result = self.run_config(hil_sensor="BME280", hil_csv=csv)
        self.assertTrue(result.success, result.errors)
        self.assertLess(self.api.events.index(("POST", "/v1/peripheral-prepare")),
                        self.api.events.index(("POST", "/v1/peripheral-program-value")))
        self.assertLess(self.api.events.index(("POST", "/v1/peripheral-program-value")),
                        self.api.events.index(("POST", "/upload")))
        report = json.loads((Path(result.output_dir) / "hil.json").read_text())
        self.assertEqual(report["sent_words"], 6)

    def test_fifty_hil_samples_are_sent_in_bounded_word_batches(self):
        result = self.run_config(hil_sensor="BME280", hil_csv=ROOT / "examples/hil/bme280.csv")
        self.assertTrue(result.success, result.errors)
        self.assertEqual([body["address"] for _, body in self.api.hil_writes], [0, 128])
        self.assertEqual([len(body["value"].splitlines()) for _, body in self.api.hil_writes], [128, 22])

    def test_queued_job_is_cancelled_before_owned_booking_release_on_timeout(self):
        self.api.job_status = "queued"
        result = self.run_config(job_timeout=0.000001)
        self.assertFalse(result.success)
        self.assertLess(self.api.events.index(("POST", "/v1/ci/jobs/101/cancel")),
                        self.api.events.index(("GET", "/cancel-booking")))

    def test_running_job_and_supplied_booking_are_not_falsely_reported_cancelled(self):
        self.api.job_status = "running"
        result = self.run_config(job_timeout=0.000001, booking_id=99)
        self.assertFalse(result.success)
        self.assertTrue(any("still running" in error["message"] for error in result.errors))
        self.assertNotIn(("POST", "/v1/ci/jobs/101/cancel"), self.api.events)
        self.assertNotIn(("GET", "/cancel-booking"), self.api.events)

    def test_hil_prepare_deadline_prevents_a_late_response_becoming_success(self):
        release, finished = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            release.wait(1)
            finished.set()
            return {"status": "okay"}
        with patch.object(self.api, "request", side_effect=delayed):
            try:
                with self.assertRaises(ECWError):
                    hil.prepare(self.api, 99, 850, timeout=0.01)
            finally:
                release.set()
                self.assertTrue(finished.wait(1))

    def test_interrupt_runs_cleanup_and_returns_interrupt_exit_code(self):
        original = self.api.request
        def request(path, **kwargs):
            if path == "/v1/artifacts/my-uploads" and kwargs.get("method") == "POST":
                raise KeyboardInterrupt("Stopped")
            return original(path, **kwargs)
        with patch.object(self.api, "request", side_effect=request):
            result = self.run_config()
        self.assertEqual(result.exit_code, 130)
        self.assertIn(("GET", "/cancel-booking"), self.api.events)

    def test_transport_bounds_json_responses(self):
        client = ECWClient("https://example.test/api", "offline-secret")
        with patch("ecw_ci_host.ecw_client.JSON_LIMIT", 8), \
             patch.object(client._opener, "open", return_value=io.BytesIO(b'{"too large":true}')):
            with self.assertRaisesRegex(ECWError, "exceeds"):
                client.request("/booking")

    def test_failed_hil_preparation_never_sends_data_or_firmware(self):
        csv = self.root / "sensor.csv"
        csv.write_text("25,50,1013\n")
        self.api.bad_hil_prepare = True
        result = self.run_config(hil_sensor="BME280", hil_csv=csv)
        self.assertFalse(result.success)
        self.assertNotIn(("POST", "/v1/peripheral-program-value"), self.api.events)
        self.assertNotIn(("POST", "/upload"), self.api.events)

    def test_invalid_hil_csv_is_rejected_before_booking(self):
        csv = self.root / "bad.csv"
        csv.write_text("999999,50,1013\n")
        with self.assertRaises(ValueError):
            self.run_config(hil_sensor="BME280", hil_csv=csv)
        self.assertEqual(self.api.events, [])

    def test_invalid_jobs_are_rejected_before_booking(self):
        jobs = self.root / "jobs"
        jobs.mkdir()
        spec = json.loads((self.config.jobs_dir / "01_serial.json").read_text())
        for update in ({"booking_id": 999}, {"duration_seconds": 1},
                       {"commands": spec["commands"] * 2}, {"metadata": {"bad": float("nan")}}):
            (jobs / "01_bad.json").write_text(json.dumps({**spec, **update}))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.run_config(jobs_dir=jobs)
        self.assertEqual(self.api.events, [])

    def test_config_paths_resolve_from_config_directory(self):
        config = RunConfig.from_file(ROOT / "examples/arduino/run.toml")
        self.assertEqual(config.jobs_dir, ROOT / "examples/arduino/jobs")
        self.assertEqual(config.firmware, ROOT / "build/arduino_ci_bench.ino.bin")

    def test_cli_validate_needs_neither_firmware_nor_token_nor_network(self):
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(["validate", "--config", str(ROOT / "examples/arduino/run.toml")])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_timezone_offsets_are_compared_as_absolute_time(self):
        self.assertEqual(timestamp("2026-11-09T12:00:00+01:00"), timestamp("2026-11-09T11:00:00Z"))
        self.assertEqual(timestamp("2026-11-09T11:00:00"), timestamp("2026-11-09T11:00:00Z"))

    def test_zip_members_are_bounded_unique_and_never_extracted(self):
        bundle = self.root / "test.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("../../outside.log", "hello")
        self.assertEqual(read_member(bundle, "outside.log"), b"hello")
        self.assertFalse((self.root.parent / "outside.log").exists())
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("a/data.log", "one")
            archive.writestr("b/data.log", "two")
        with self.assertRaises(ECWError):
            read_member(bundle, "data.log")

    def test_transport_redacts_http_error_and_does_not_retry_mutation(self):
        client = ECWClient("https://example.test/api", "offline-secret")
        error = urllib.error.HTTPError("https://example.test", 403, "Denied", {}, io.BytesIO(b"offline-secret denied"))
        with patch.object(client._opener, "open", side_effect=error) as request:
            with self.assertRaises(ECWError) as raised:
                client.request("/upload", method="POST", body={})
        self.assertNotIn("offline-secret", str(raised.exception))
        self.assertIn("HTTP 403", str(raised.exception))
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
