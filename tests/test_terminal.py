from qa_app.workflow import terminal


def test_known_lines_become_plain_updates():
    assert "Installing Playwright" in terminal.friendly("$ npm install")
    assert "Chromium" in terminal.friendly("Downloading Chromium 140.0.7339.16 (playwright build v1187)")
    assert terminal.friendly("Running 6 tests using 2 workers") == "Playwright started: 6 tests (2 workers)."
    assert terminal.friendly("Running 1 test using 1 worker") == "Playwright started: 1 test (1 worker)."
    assert terminal.friendly("  ✓  1 [chromium] › SCRUM-8.spec.ts:4:1 › [1] opens (1.2s)") is None  # checks are reported elsewhere


def test_a_stall_says_what_was_last_seen_and_how_to_unblock():
    msg = terminal.stall_message("No output for 45s. Last line: Ok to proceed? (y)")
    assert "silent for 45s" in msg and "Ok to proceed? (y)" in msg and "Stop" in msg
    assert "install" in msg.lower()  # the prompt means Playwright is missing
    assert "Chromium" in terminal.stall_message("No output for 60s. Last line: browserType.launch: Executable doesn't exist at /x")
    assert "reach" in terminal.stall_message("No output for 50s. Last line: page.goto: net::ERR_NAME_NOT_RESOLVED at https://x")
    assert "Stop" in terminal.stall_message("No output for 45s. Last line: (nothing printed yet)")
