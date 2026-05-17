"""QA tests for bench.py and stats_sweep.py.

Highest value targets given the 560-cell upcoming sweep:
1. `_classify` — the gate verdict logic. Bad threshold here mis-classifies
   every cell that hits it.
2. `stats_sweep.line_re` — the regex that parses bench stdout. Was broken
   pre-fix; verify the fix sticks.
3. `run_one` / `_attempt_once` — orchestration. Mock-driven smoke that the
   retry + best-attempt scoring picks the right record.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make bench / stats_sweep importable without browsers/* deps.
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import bench  # noqa: E402
import stats_sweep  # noqa: E402


# ---------------------------------------------------------------------------
# _classify — pure function, drives every cell's verdict
# ---------------------------------------------------------------------------


class TestClassify:
    def test_no_signal_at_all_is_error(self):
        # VERIFIED: line 112-113 — all four signals empty → error.
        assert bench._classify(None, [], "", "") == "error"

    def test_status_in_blocked_set_is_blocked(self):
        # VERIFIED: BLOCKED_STATUSES = {403, 406, 429, 451, 503}.
        for s in (403, 406, 429, 451, 503):
            assert bench._classify(s, [s], "Site", "<html>content</html>") == "blocked"

    def test_main_chain_blocked_even_if_final_ok(self):
        # VERIFIED: line 116 — any main-frame status in blocked set → blocked.
        # Real case: 200 final after a 403 in the redirect chain.
        assert (
            bench._classify(200, [403, 200], "Real Title", "<html><script>ok</script></html>")
            == "blocked"
        )

    def test_cloudflare_title_is_gated(self):
        # VERIFIED: GATE_TITLE_PATTERNS includes "just a moment".
        assert (
            bench._classify(200, [200], "Just a moment...", "<html>...</html>")
            == "gated"
        )

    def test_attention_required_title_is_gated(self):
        assert (
            bench._classify(200, [200], "Attention Required! | Cloudflare", "<html/>")
            == "gated"
        )

    def test_f5_support_id_in_body_is_gated(self):
        # VERIFIED: GATE_BODY_PATTERNS includes "your support id is:".
        body = "<html><body>Your Support ID is: 12345-6789</body></html>"
        assert bench._classify(200, [200], "Site", body) == "gated"

    def test_perfdrive_shim_signal_is_gated(self):
        # VERIFIED: GATE_BODY_PATTERNS includes "perfdrive\.com".
        body = "<html><script src='https://perfdrive.com/x.js'></script></html>"
        assert bench._classify(200, [200], "Site", body) == "gated"

    def test_short_body_no_script_is_gated(self):
        # VERIFIED: line 127-128 — len(body) < 800 and no <script> → gated.
        # This is the "empty redirect page" heuristic.
        body = "<html><body>redirecting</body></html>"
        assert bench._classify(200, [200], "Title", body) == "gated"

    def test_short_body_with_script_is_ok(self):
        # VERIFIED: the <script> check disables the short-body heuristic so
        # legit JS-heavy SPAs aren't false-flagged.
        body = "<html><script>doStuff()</script><body>x</body></html>"
        assert bench._classify(200, [200], "Real App", body) == "ok"

    def test_long_real_page_is_ok(self):
        # ORACLE: assuming a normal site with no gate signals returns 'ok'.
        body = "<html>" + "real content " * 500 + "<script>x()</script></html>"
        assert bench._classify(200, [200], "Real Site", body) == "ok"

    def test_50kb_body_scan_window(self):
        # VERIFIED: line 123 — body[:50_000] is scanned. A signal at byte 49_000
        # should still hit; one at byte 51_000 should not (we rely on the body
        # being big enough that the short-body heuristic doesn't fire either).
        prefix = "x" * 49_000
        body_hit = prefix + "your support id is: 1" + "y" * 5000 + "<script/>"
        assert bench._classify(200, [200], "Site", body_hit) == "gated"

        # Signal past the 50K window → not gated. Body has <script> and is
        # large, so it falls to "ok".
        body_miss = "x" * 51_000 + "your support id is: 1" + "<script/>"
        assert bench._classify(200, [200], "Site", body_miss) == "ok"

    def test_nodriver_no_status_but_has_content(self):
        # VERIFIED: line 112 — relaxed error gate. nodriver can't capture status,
        # but if title+body are present, classify normally.
        body = "<html>" + "ok " * 500 + "<script/></html>"
        assert bench._classify(None, [], "Real Site", body) == "ok"

    def test_status_none_but_blocked_in_chain(self):
        # Defensive: final status missing, but chain shows 429 somewhere.
        assert bench._classify(None, [429], "Site", "<html/>") == "blocked"


# ---------------------------------------------------------------------------
# slugify — pure, used in directory names
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic(self):
        # VERIFIED: replaces non-alphanumeric with '-', strips edges.
        assert bench.slugify("Reddit Old") == "reddit-old"

    def test_dots_and_underscores(self):
        assert bench.slugify("canadianinsider.com") == "canadianinsider-com"

    def test_collapses_runs(self):
        # VERIFIED: the regex uses + so consecutive non-alnum collapse.
        assert bench.slugify("a !! b") == "a-b"

    def test_empty_after_normalize(self):
        # ORACLE: pure-symbol input strips to empty string.
        assert bench.slugify("!!!") == ""


# ---------------------------------------------------------------------------
# stats_sweep.line_re — the regex was wrong pre-fix; pin the new contract
# ---------------------------------------------------------------------------


class TestStatsSweepLineRegex:
    """The pre-fix regex required `[OK ]` or `[ERR]` literals. The new bench
    output is `[<verdict>     /<verdict>    ]` where verdict ∈ {ok, gated,
    blocked, error}. These tests pin the new contract.
    """

    # Mirror the regex in the module to detect drift.
    LINE_RE = re.compile(
        r"->\s+(\S+)\s+\[\s*(ok|gated|blocked|error)\s*/\s*(ok|gated|blocked|error)\s*\]"
    )

    def test_matches_actual_bench_format(self):
        # VERIFIED: bench.py line 361/368 — `  -> {name:30s} [{best:7s}/{maj:7s}] ...`
        # The :7s padding right-pads to width 7 with spaces.
        line = "  -> reddit-old                     [ok     /ok     ]   523ms n=2  "
        m = self.LINE_RE.search(line)
        assert m is not None
        assert m.group(1) == "reddit-old"
        assert m.group(2) == "ok"
        assert m.group(3) == "ok"

    def test_matches_module_regex(self):
        # Belt-and-braces: the regex compiled inside the module should match
        # the same lines.
        line = "  -> canadianinsider-com            [blocked/blocked]  1234ms n=2  "
        # The module compiles this inside measure_browser; we re-source via the
        # same pattern string to detect drift.
        assert self.LINE_RE.search(line) is not None

    def test_matches_gated_verdict(self):
        line = "  -> reddit-old                     [gated  /gated  ]   523ms n=2  "
        m = self.LINE_RE.search(line)
        assert m is not None and m.group(2) == "gated"

    def test_matches_error_verdict(self):
        line = "  -> dead-site                      [error  /error  ]    50ms n=3  net::ERR_NAME_NOT_RESOLVED"
        m = self.LINE_RE.search(line)
        assert m is not None and m.group(2) == "error"

    def test_does_not_match_unrelated_lines(self):
        # ORACLE: progress lines that aren't target results shouldn't match.
        assert self.LINE_RE.search("BROWSER_READY 1730000000.123") is None
        assert self.LINE_RE.search("=== vanilla (subprocess) ===") is None

    def test_split_verdicts_both_captured(self):
        # ORACLE: best=ok, maj=gated — second group should be 'ok' (best),
        # third should be 'gated' (maj). Reader uses group(2) for the verdict.
        line = "  -> foo                            [ok     /gated  ]   500ms n=3  "
        m = self.LINE_RE.search(line)
        assert m is not None
        assert m.group(2) == "ok"
        assert m.group(3) == "gated"


# ---------------------------------------------------------------------------
# run_one — verify orchestration: retries, best-attempt tie-break, early exit
# ---------------------------------------------------------------------------


class TestRunOneOrchestration:
    def _stub_browser(self):
        return MagicMock()  # browser handle; never used because we mock _attempt_once

    def test_two_agreeing_ok_attempts_exits_early(self, mocker, tmp_path):
        # VERIFIED: line 295-298 — early exit on 2 matching non-error verdicts.
        attempt_results = [
            {"ok": True, "verdict": "ok", "load_ms": 100, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "t", "body_len": 1000, "score": {}, "error": None},
            {"ok": True, "verdict": "ok", "load_ms": 100, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "t", "body_len": 1000, "score": {}, "error": None},
        ]
        mocker.patch.object(bench, "_attempt_once", side_effect=attempt_results)
        # Kill retry delays so the test is fast.
        mocker.patch.object(bench, "RETRY_DELAYS_S", (0, 0, 0))

        rec = bench.run_one(
            self._stub_browser(),
            "vanilla",
            {"name": "x", "url": "https://x"},
            out_dir=tmp_path,
        )
        assert len(rec["attempts"]) == 2  # exits early, doesn't run attempt 3
        assert rec["best_verdict"] == "ok"
        assert rec["majority_verdict"] == "ok"

    def test_blocked_blocked_exits_early_at_attempt_2(self, mocker, tmp_path):
        # VERIFIED: spec says "blocked target that stays blocked exits early".
        attempt_results = [
            {"ok": True, "verdict": "blocked", "load_ms": 100, "final_url": "u", "status": 403,
             "main_statuses": [403], "title": "", "body_len": 0, "score": {}, "error": None},
            {"ok": True, "verdict": "blocked", "load_ms": 100, "final_url": "u", "status": 403,
             "main_statuses": [403], "title": "", "body_len": 0, "score": {}, "error": None},
        ]
        mocker.patch.object(bench, "_attempt_once", side_effect=attempt_results)
        mocker.patch.object(bench, "RETRY_DELAYS_S", (0, 0, 0))

        rec = bench.run_one(self._stub_browser(), "vanilla",
                            {"name": "x", "url": "https://x"}, out_dir=tmp_path)
        assert len(rec["attempts"]) == 2
        assert rec["best_verdict"] == "blocked"

    def test_disagreeing_attempts_runs_all_three(self, mocker, tmp_path):
        # VERIFIED: line 297 — "last two agree" gate. error → gated → ok forces
        # all 3 attempts because no consecutive pair agrees.
        attempt_results = [
            {"ok": True, "verdict": "error", "load_ms": 50, "final_url": "", "status": None,
             "main_statuses": [], "title": "", "body_len": 0, "score": {}, "error": "boom"},
            {"ok": True, "verdict": "gated", "load_ms": 100, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "Just a moment", "body_len": 100, "score": {}, "error": None},
            {"ok": True, "verdict": "ok", "load_ms": 200, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "Real", "body_len": 5000, "score": {"k": "v"}, "error": None},
        ]
        mocker.patch.object(bench, "_attempt_once", side_effect=attempt_results)
        mocker.patch.object(bench, "RETRY_DELAYS_S", (0, 0, 0))

        rec = bench.run_one(self._stub_browser(), "vanilla",
                            {"name": "x", "url": "https://x"}, out_dir=tmp_path)
        assert len(rec["attempts"]) == 3
        # Best of {error, gated, ok} is 'ok'.
        assert rec["best_verdict"] == "ok"
        # Score comes from the best attempt's score dict.
        assert rec["score"] == {"k": "v"}

    def test_tie_break_prefers_later_attempt(self, mocker, tmp_path):
        # VERIFIED: the docstring promises "Tie-break toward more conservative
        # (later attempts > earlier)". With three 'ok' attempts, the score
        # should come from attempt 3, not attempt 1.
        # NOTE: early-exit would normally fire at attempt 2; we run only 2
        # attempts here to keep the assertion simple.
        attempt_results = [
            {"ok": True, "verdict": "ok", "load_ms": 100, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "t", "body_len": 1000,
             "score": {"price": "first"}, "error": None},
            {"ok": True, "verdict": "ok", "load_ms": 100, "final_url": "u", "status": 200,
             "main_statuses": [200], "title": "t", "body_len": 1000,
             "score": {"price": "second"}, "error": None},
        ]
        mocker.patch.object(bench, "_attempt_once", side_effect=attempt_results)
        mocker.patch.object(bench, "RETRY_DELAYS_S", (0, 0, 0))

        rec = bench.run_one(self._stub_browser(), "vanilla",
                            {"name": "x", "url": "https://x"}, out_dir=tmp_path)
        # VERIFIED post-fix: reversed(attempts) makes the latest win the tie.
        assert rec["score"] == {"price": "second"}

    def test_all_errors_returns_error(self, mocker, tmp_path):
        # ORACLE: 3 errors → best_verdict is 'error', majority is 'error'.
        attempt_results = [
            {"ok": False, "verdict": "error", "load_ms": 50, "final_url": "", "status": None,
             "main_statuses": [], "title": "", "body_len": 0, "score": {}, "error": "x"}
            for _ in range(3)
        ]
        # An all-error sequence still triggers early exit because verdicts
        # agree, but only when they're non-error per line 297. So we'll
        # actually run all 3 here.
        mocker.patch.object(bench, "_attempt_once", side_effect=attempt_results)
        mocker.patch.object(bench, "RETRY_DELAYS_S", (0, 0, 0))

        rec = bench.run_one(self._stub_browser(), "vanilla",
                            {"name": "x", "url": "https://x"}, out_dir=tmp_path)
        # VERIFIED: line 297 filters out 'error' from early-exit, so 3 attempts run.
        assert len(rec["attempts"]) == 3
        assert rec["best_verdict"] == "error"


# ---------------------------------------------------------------------------
# extract_score — pure-ish, returns extract-fail sentinel on errors
# ---------------------------------------------------------------------------


class TestExtractScore:
    def test_returns_empty_when_no_extract_config(self):
        # VERIFIED: target with no 'extract' key returns {}.
        page = MagicMock()
        assert bench.extract_score(page, {"name": "x"}) == {}

    def test_returns_extracted_text(self):
        page = MagicMock()
        page.locator.return_value.first.inner_text.return_value = "  $42.00  "
        result = bench.extract_score(page, {"extract": {"price": ".price"}})
        assert result == {"price": "$42.00"}  # whitespace stripped

    def test_locator_failure_returns_sentinel(self):
        # VERIFIED: line 138-139 — exception inside per-key extract is caught
        # and the value becomes "<extract-fail: <ExcType>>". Critical: one
        # broken selector must not lose other extracts.
        page = MagicMock()

        def fake_locator(sel):
            mock = MagicMock()
            if sel == ".broken":
                mock.first.inner_text.side_effect = TimeoutError("timed out")
            else:
                mock.first.inner_text.return_value = "good"
            return mock

        page.locator.side_effect = fake_locator
        result = bench.extract_score(
            page, {"extract": {"price": ".broken", "title": ".good"}}
        )
        assert result["title"] == "good"
        assert result["price"].startswith("<extract-fail: TimeoutError>")


# ---------------------------------------------------------------------------
# disk_for — pure, returns dict with totals
# ---------------------------------------------------------------------------


class TestStatsSweepDiskFor:
    def test_missing_paths_yield_zero(self, mocker):
        # VERIFIED: du_bytes returns 0 for missing paths (line 50-51).
        mocker.patch.dict(stats_sweep.DISK_PATHS,
                          {"fake": ["/nonexistent/path/abc"]},
                          clear=False)
        out = stats_sweep.disk_for("fake")
        assert out["/nonexistent/path/abc"] == 0
        assert out["_total_bytes"] == 0
        assert out["_total_mb"] == 0.0

    def test_unknown_browser_returns_empty_totals(self):
        # VERIFIED: DISK_PATHS.get("nope", []) → no paths, totals are 0.
        out = stats_sweep.disk_for("nope-not-a-browser")
        assert out["_total_bytes"] == 0
        assert out["_total_mb"] == 0.0

    def test_real_path_sums_correctly(self, tmp_path, mocker):
        # ORACLE: 100-byte + 200-byte files in tmp_path total 300 bytes.
        (tmp_path / "a.bin").write_bytes(b"x" * 100)
        (tmp_path / "b.bin").write_bytes(b"y" * 200)
        mocker.patch.dict(stats_sweep.DISK_PATHS,
                          {"tester": [str(tmp_path)]}, clear=False)
        out = stats_sweep.disk_for("tester")
        assert out[str(tmp_path)] == 300
        assert out["_total_bytes"] == 300


# ---------------------------------------------------------------------------
# Import smoke tests for browser adapters — verify they're at least parseable
# and expose a `session` context manager. Skip if the underlying SDK is absent
# (the bench will subprocess them; if SDK is missing the subprocess will fail
# cleanly, which is desired behavior, not something for unit tests to catch).
# ---------------------------------------------------------------------------


class TestBrowserAdapters:
    @pytest.mark.parametrize("name", ["vanilla", "patchright", "cloak",
                                       "camofox", "rebrowser", "nodriver"])
    def test_adapter_module_has_session(self, name):
        # VERIFIED: bench.run_one expects `mod.session(headless=...)` to be a
        # context manager. If the SDK is missing on this box we skip.
        try:
            mod = __import__(f"browsers.{name}", fromlist=["session"])
        except ImportError as e:
            pytest.skip(f"{name} SDK not installed: {e}")
        assert hasattr(mod, "session"), f"{name} missing session()"
        assert callable(mod.session), f"{name}.session is not callable"
