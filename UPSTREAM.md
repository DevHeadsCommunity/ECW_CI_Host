# Upstream extraction

This first version abstracts the Python scripts from
[ECW_CI_Github_Actions_Templates](https://github.com/DevHeadsCommunity/ECW_CI_Github_Actions_Templates/tree/327b344818615992cdbc012f3a8762b095ee6fd6/.github/scripts),
revision `327b344818615992cdbc012f3a8762b095ee6fd6` (`main`).
[upstream-sources.json](upstream-sources.json) records SHA256 hashes of the source files at that revision. The original MIT copyright is preserved in [LICENSE](LICENSE).

The extraction retains the HTTP operations and protocols used by the template. Provider environment variables, output-file writers, and fixed project paths are replaced by function parameters and returned Python objects. No changes are made to the template or the backend.

| Template source under `.github/scripts/` | Portable implementation under `src/ecw_ci_host/` | Extraction and additions |
| --- | --- | --- |
| `ecw_client.py` | `ecw_client.py`, adapted by `client.py` | Keep JSON requests, API-key headers, WAF-compatible User-Agent, byte transfer, and multipart assembly. Remove GitHub writers. Add response bounds, redacted errors, no credential-bearing redirects, and injected opener. |
| `select_board.py` | `select_board.py:select_board` | Keep catalog response variants and name filtering. Return the selected row; prefer exact names and reject ambiguity. |
| `find_or_create_booking.py` | `find_or_create_booking.py` | Parameterize the existing lookup/create helpers. Return `(booking, created)` so callers can preserve reused reservations. |
| `wait_for_booking.py` | `wait_for_booking.py` | Keep UTC conversion (including naive UTC timestamps), active/window checks, terminal rejection, and adaptive polling. Add caller timeout/observer. |
| `upload_firmware.py` | `upload_firmware.py:upload_firmware` | Keep safe basename, storage-only upload, success check, and stored-filename manifest verification. Accept a provided image path, BIN/HEX, and add content fingerprint. |
| `flash_firmware.py` | `flash_firmware.py:flash_firmware` | Keep distinct explicit flash request, 180-second request timeout, and `okay` requirement. Accept the uploaded filename directly. |
| `upload_and_flash.py` | `firmware.py:upload_and_flash` | Compose the two extracted operations and save their separate outcomes. |
| `configure_hil.py` | `configure_hil.py`, adapted by `hil.py` | Keep sensor selection, saved configuration ID, preparation worker/deadline, and 128-word CSV writes. Replace environment inputs with client, booking, sensor, values, and report arguments. |
| `hil_csv.py`, `hil_profiles/*.json` | Same relative filenames | Copied byte-for-byte, including frontend-compatible unit encoding and scaling. |
| `create_jobs.py` | `create_jobs.py`, adapted by `jobs.py` | Keep sorted JSON loading, numeric-prefix labels, and submission. Return job IDs directly; add unique run provenance and local validation. |
| `poll_jobs.py` | `poll_jobs.py`, adapted by `jobs.py` | Keep backend terminal statuses and polling. Return final job; caller saves observations, results, and paginated logs. |
| `download_artifacts.py` | `download_artifacts.py` | Parameterize job ID and destination. Use the extracted byte-transfer helper through the client adapter. Required collection failures propagate to the run result. |

New code supplies `RunConfig`, CLI parsing, `run_test()` orchestration, booking ownership/identity checks and cleanup, evidence directories, optional assertions, and the general Arduino bench. These replace the coordination previously performed by a provider workflow. There are no included CI-provider workflows or activation callbacks.

To update later, compare the pinned source hashes with the desired template revision, port protocol changes into the extracted modules, and run the offline checks before qualifying the change against hardware. Hardware behavior is not established by the offline stand-ins.
