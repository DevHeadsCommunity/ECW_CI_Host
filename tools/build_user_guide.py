"""Rebuild the two-page Word guide (authoring dependencies, not runtime deps).

python -m pip install python-docx==1.2.0 cairosvg==2.8.2
python tools/build_user_guide.py
"""

from io import BytesIO
from pathlib import Path

import cairosvg
from docx import Document
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
document = Document()
section = document.sections[0]
section.page_width, section.page_height = Cm(21), Cm(29.7)
section.top_margin = section.bottom_margin = Cm(1.6)
section.left_margin = section.right_margin = Cm(1.8)
normal = document.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10)
normal.paragraph_format.space_after = Pt(4)
normal.paragraph_format.line_spacing = 1
for name in ("Title", "Heading 1", "Heading 2"):
    document.styles[name].font.color.rgb = RGBColor.from_string("14584F")
document.styles["Title"].font.size = Pt(25)
document.styles["Title"].paragraph_format.space_after = Pt(5)
for name in ("Heading 1", "Heading 2"):
    document.styles[name].font.size = Pt(13)
    document.styles[name].paragraph_format.space_before = Pt(9)
    document.styles[name].paragraph_format.space_after = Pt(4)


def paragraph(text, style=None):
    return document.add_paragraph(text, style)


def table(headings, rows):
    result = document.add_table(rows=1, cols=len(headings))
    result.style = "Light Shading Accent 1"
    result.autofit = False
    result.columns[0].width = Cm(4.1)
    result.columns[1].width = Cm(13.3)
    for cell, text in zip(result.rows[0].cells, headings):
        cell.text = text
    for row in rows:
        for cell, text in zip(result.add_row().cells, row):
            cell.text = text
    for row in result.rows:
        for index, cell in enumerate(row.cells):
            cell.width = Cm(4.1 if index == 0 else 13.3)
            for item in cell.paragraphs:
                item.paragraph_format.space_after = Pt(2)
                item.paragraph_format.line_spacing = 1
                for run in item.runs:
                    run.font.size = Pt(9.5)
    return result


document.add_heading("ECW CI Host", 0)
paragraph("USER GUIDE · FIRST VERSION 0.1.0")
paragraph("One Python library and CLI for booking hardware, configuring optional HIL, uploading and flashing firmware, running tests, and collecting evidence. Use the same workflow from GitHub Actions, Jenkins, or a local terminal.")
image = cairosvg.svg2png(url=str(ROOT / "docs/architecture.svg"), output_width=1680)
document.add_picture(BytesIO(image), width=Cm(15.5))
document.add_heading("From available hardware to a test result", level=1)
paragraph("An ECW administrator registers each board's programming and serial connections, availability, and optional camera/HIL equipment. The host requests a published board type; ECW prepares and manages the booked hardware. The CI runner only needs HTTPS access to ECW.")
table(("Use case", "Expected evidence"), (
    ("Firmware regression", "Expected serial output and consecutive sample counters"),
    ("HIL replay", "Physical-value CSV programming plus project-specific MCU assertions"),
    ("Visual capture", "An optional linked camera image for review"),
    ("Local reproduction", "The same configuration and evidence as the CI run"),
))
document.add_heading("First test: Arduino UNO R4 WiFi", level=1)
paragraph("Prerequisites: Python 3.11+, Arduino CLI 1.3.1, an ECW API key, and access to an available Arduino UNO R4 WiFi. Provide ECW_API_KEY through your shell or CI secret manager.")
for line in (
    "Install the package: python -m pip install .",
    "Build firmware: bash examples/arduino/build.sh",
    "Run: ecw-ci run --config examples/arduino/run.toml",
):
    paragraph(line, "List Number")
paragraph("The sketch turns the built-in LED on and emits one numbered heartbeat per second. The five-second serial job must contain at least four consecutive samples reporting LED=ON. This verifies execution and the reported GPIO state, not optical light output.")

document.add_page_break()
document.add_heading("Use the same host from any runner", level=1)
table(("Environment", "Setup and trigger"), (
    ("Any CI runner", "Inject ECW_API_KEY through the runner credential store. Run bash examples/arduino/run.sh and archive artifacts/** even on failure."),
    ("Own firmware", "Run your build command, then ecw-ci run --config project.toml. The CLI takes an already-built image and ordered JSON jobs."),
    ("Terminal", "ecw-ci run --config examples/arduino/run.toml. edgebench-hil is an alias for ecw-ci."),
    ("Python", "from ecw_ci_host import RunConfig, run_test; call run_test(config) and inspect result.success or result.exit_code."),
))
document.add_heading("Inputs and lifecycle", level=1)
paragraph("Provide the exact board type name, a built .bin/.hex file, an ordered directory of JSON jobs, and an output directory. TOML/JSON configuration paths resolve from the configuration file. Optional HIL uses hil_sensor and hil_csv or the matching CLI options.")
paragraph("Book → wait for active status → optional HIL preparation/CSV → upload to NFS → separate explicit flash → jobs → evidence checks → owned booking release. The template Python scripts are extracted into callable functions; the CLI connects them without provider environment/output files.")
paragraph("Without booking_id the host reuses an existing booking or creates one. Reused bookings are preserved. A supplied booking must belong to the account and match the requested MCU; it is never extended or cancelled by the host. A short CI-created slot can be extended once through ECW's normal rules. Maintenance must be closed before a new session can activate.")
document.add_heading("Read the result", level=1)
paragraph("The CLI prints JSON. Exit 0 means passed, 1 means workflow/verification/cleanup failure, 2 means invalid inputs or startup failure, and 130 means interrupted. Each invocation has a new artifacts/<run-id>/ directory.")
table(("File", "What to inspect"), (
    ("summary.json", "Overall status, booking/job IDs, errors, and exit code"),
    ("firmware.json / hil.json", "Firmware SHA256 and upload/flash state; optional HIL progress"),
    ("jobs/<label>/", "requests, results, logs, artifacts.zip, checks, collection errors"),
    ("release.json", "Release acknowledgement for a booking created by the run"),
))
document.add_heading("When something fails", level=1)
paragraph("Authentication: check the key and account eligibility. Confirmed booking: check availability, activation, and maintenance. Flash failure: tests do not start. Successful capture with failed assertions: inspect checks.json. Missing camera: link the correct feed first.")
paragraph("Normal failures and handled interrupts attempt cleanup. Only queued jobs can be cancelled through the current job API; running jobs remain bounded by backend deadlines. Force-killing a runner can prevent client cleanup. Offline checks do not qualify physical hardware.")
paragraph("Technical configuration, API routes, job schemas, optional HIL, and limitations: README.md. Repository: github.com/DevHeadsCommunity/ECW_CI_Host")

footer = section.footer.paragraphs[0]
footer.text = "ECW CI Host · v0.1.0 · Mohamed Taher MASROUKI"
footer.runs[0].font.size = Pt(9)
document.core_properties.author = "Mohamed Taher MASROUKI"
document.core_properties.title = "ECW CI Host — User Guide"
document.core_properties.subject = "Portable hardware automation and Arduino runner testbench"
target = ROOT / "docs/ECW-CI-User-Guide.docx"
document.save(target)
print(target)
