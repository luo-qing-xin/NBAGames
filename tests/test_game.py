from __future__ import annotations

import copy
import json
import os
from itertools import pairwise
from pathlib import Path

import pytest
import requests

from nba_pbp.common.errors import ResponseValidationError, StorageError
from nba_pbp.game import cli
from nba_pbp.game.collector import Collector
from nba_pbp.game.resources import (
    BY_NAME,
    PROFILE,
    RESOURCES,
    game_season,
    inspect_response,
)
from nba_pbp.game.storage import atomic_json
from nba_pbp.game.transport import RequestFailure, Response, Transport

GAME = "0022300001"


def dataset(name, headers, rows):
    return {"name": name, "headers": headers, "rowSet": rows}


def payload(resource, *, status=3, person_id=None):
    if person_id is not None:
        return {
            "resultSets": [
                dataset(
                    "CommonPlayerInfo", ["PERSON_ID", "HEIGHT"], [[person_id, "6-8"]]
                ),
                dataset("AvailableSeasons", ["SEASON_ID"], [[2023]]),
            ],
            "unknownProfileField": {"keep": True},
        }
    if resource.root:
        root = {"gameId": GAME, "unknown": {"nested": [1, None, "原始"]}}
        if resource.name in ("play_by_play_v3", "live_play_by_play"):
            root["actions"] = [
                {"actionNumber": 1, "description": "keep unchanged", "unknown": [3, 4]}
            ]
        else:
            root["homeTeam"] = {
                "players": [{"personId": 1}],
                "statistics": {"points": 100},
            }
            root["awayTeam"] = {
                "players": [{"personId": 2}],
                "statistics": {"points": 98},
            }
            if resource.name == "box_score_matchups_v3":
                for side in ("homeTeam", "awayTeam"):
                    root[side]["players"][0]["matchups"] = [
                        {"personId": 4, "statistics": {"matchupMinutes": "1:00"}}
                    ]
            if resource.name == "box_score_summary_v3":
                root["homeTeam"]["inactives"] = [{"personId": 3}, {"personId": 1}]
                root["awayTeam"]["inactives"] = []
            if resource.name in ("box_score_summary_v3", "live_box_score"):
                root["gameStatus"] = status
        return {
            resource.root: root,
            "meta": {"version": 1},
            "unknownTopLevel": ["retained"],
        }
    if resource.module == "shotchartdetail":
        return {
            "resultSets": [
                dataset(
                    "Shot_Chart_Detail",
                    ["GAME_ID", "SHOT_MADE_FLAG"],
                    [[GAME, 0], [GAME, 1]],
                ),
                dataset("LeagueAverages", ["FGA"], [[100]]),
            ]
        }
    return {
        "resultSets": [
            dataset(name, ["GAME_ID", "PERSON_ID"], [[GAME, i + 1]])
            for i, name in enumerate(resource.datasets)
        ]
    }


class FakeTransport:
    def __init__(self, *, failures=(), overrides=None, status=3, interrupt=None):
        self.calls = []
        self.failures = set(failures)
        self.overrides = overrides or {}
        self.status = status
        self.interrupt = interrupt

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def fetch(self, resource, game_id, person_id=None):
        key = resource.name if person_id is None else f"common_player_info:{person_id}"
        self.calls.append(key)
        if key == self.interrupt:
            raise KeyboardInterrupt
        if key in self.failures:
            raise RequestFailure("连接 NBA API 超时", 2, {"GameID": game_id})
        raw = copy.deepcopy(
            self.overrides.get(
                key, payload(resource, status=self.status, person_id=person_id)
            )
        )
        return Response(
            raw,
            {"GameID": game_id} if person_id is None else {"PlayerID": person_id},
            1,
        )


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not access the network")

    monkeypatch.setattr(requests.Session, "get", blocked)
    from curl_cffi import requests as curl_requests

    monkeypatch.setattr(curl_requests.Session, "get", blocked)


def run(tmp_path, transport=None, **kwargs):
    transport = transport or FakeTransport()
    report = Collector(
        GAME, tmp_path, transport=transport, progress=lambda _: None, **kwargs
    ).run()
    return report, transport


def test_every_official_endpoint_builds_without_sending_request():
    assert len(RESOURCES) == len({r.module for r in RESOURCES}) == 13
    for resource in RESOURCES:
        request = resource.request(GAME)
        assert request.parameters["GameID"] == GAME
    shots = BY_NAME["shot_chart_detail"].request("0042300401").parameters
    assert shots["TeamID"] == shots["PlayerID"] == 0
    assert shots["ContextMeasure"] == "FGA"
    assert shots["Season"] == "2023-24"
    assert shots["SeasonType"] == "Playoffs"
    for name in ("box_score_advanced_v3", "box_score_traditional_v3"):
        params = BY_NAME[name].request(GAME).parameters
        assert all(
            str(params[k]) == "0"
            for k in ("StartPeriod", "EndPeriod", "StartRange", "EndRange", "RangeType")
        )


@pytest.mark.parametrize(
    ("game_id", "season", "kind"),
    [
        ("0029600001", "1996-97", "Regular Season"),
        ("0012300001", "2023-24", "Pre Season"),
        ("0032300001", "2023-24", "All Star"),
        ("0052300001", "2023-24", "PlayIn"),
    ],
)
def test_season_and_competition(game_id, season, kind):
    assert game_season(game_id) == (season, kind)


def test_collects_all_raw_json_and_deduplicated_profiles(tmp_path):
    report, transport = run(tmp_path)
    assert report["status"] == "complete"
    assert report["summary"]["game_resources_succeeded"] == 13
    assert report["profiles"]["person_ids"] == [1, 2, 3]
    assert transport.calls == [r.name for r in RESOURCES] + [
        f"common_player_info:{i}" for i in (1, 2, 3)
    ]
    directory = tmp_path / GAME
    files = [p for p in directory.rglob("*") if p.is_file()]
    assert len(files) == 17
    assert all(p.suffix == ".json" for p in files)
    assert json.loads(
        (directory / "raw/box_score_traditional_v3.json").read_text()
    ) == payload(RESOURCES[1])
    assert json.loads((directory / "profiles/1.json").read_text()) == payload(
        PROFILE, person_id=1
    )
    assert "fetched_at" in report["resources"]["common_player_info:1"]


def test_complete_final_game_uses_cache_without_network(tmp_path):
    run(tmp_path)
    report, transport = run(tmp_path)
    assert transport.calls == []
    assert report["status"] == "complete"
    assert all(entry["cache_hit"] for entry in report["resources"].values())


def test_partial_failure_continues_and_only_missing_resources_are_retried(tmp_path):
    first, transport = run(
        tmp_path,
        FakeTransport(failures=("box_score_advanced_v3", "common_player_info:3")),
    )
    assert first["status"] == "partial"
    assert "box_score_matchups_v3" in transport.calls
    assert first["summary"]["profiles_succeeded"] == 2
    second, transport = run(tmp_path)
    assert second["status"] == "complete"
    assert transport.calls == ["box_score_advanced_v3", "common_player_info:3"]


def test_live_fallback_preserves_missing_stats_and_partial_roster(tmp_path):
    report, _ = run(
        tmp_path,
        FakeTransport(
            failures=(
                "box_score_summary_v3",
                "box_score_traditional_v3",
                "play_by_play_v3",
            )
        ),
    )
    assert report["status"] == "partial"
    assert not report["profiles"]["roster_complete"]
    assert report["profiles"]["person_ids"] == [1, 2]
    assert report["resources"]["live_play_by_play"]["status"] == "success"
    assert report["resources"]["live_box_score"]["source"] == "nba_live_cdn"
    assert set(report["summary"]["failed_resources"]) == {
        "box_score_summary_v3",
        "box_score_traditional_v3",
        "play_by_play_v3",
    }
    assert (tmp_path / GAME / "raw/live_box_score.json").is_file()


def test_empty_data_is_preserved_and_distinguished_from_failure(tmp_path):
    shots = payload(BY_NAME["shot_chart_detail"])
    shots["resultSets"][0]["rowSet"] = []
    rotation = payload(BY_NAME["game_rotation"])
    for ds in rotation["resultSets"]:
        ds["rowSet"] = []
    report, _ = run(
        tmp_path,
        FakeTransport(
            overrides={"shot_chart_detail": shots, "game_rotation": rotation}
        ),
    )
    assert report["status"] == "complete"
    assert set(report["summary"]["empty_resources"]) == {
        "shot_chart_detail",
        "game_rotation",
    }
    assert (
        json.loads((tmp_path / GAME / "raw/shot_chart_detail.json").read_text())
        == shots
    )


def test_missing_manifest_is_reconstructed_from_raw_json(tmp_path):
    run(tmp_path)
    (tmp_path / GAME / "manifest.json").unlink()
    report, transport = run(tmp_path)
    assert transport.calls == []
    assert report["status"] == "complete"


def test_orphan_rotation_without_game_identity_is_refetched(tmp_path):
    rotation = {
        "resultSets": [
            dataset(name, ["PERSON_ID"], [[1]]) for name in ("AwayTeam", "HomeTeam")
        ]
    }
    run(tmp_path, FakeTransport(overrides={"game_rotation": rotation}))
    # Matching request parameters and checksum supply cache provenance.
    _, transport = run(tmp_path)
    assert not transport.calls
    (tmp_path / GAME / "manifest.json").unlink()
    report, transport = run(tmp_path)
    assert transport.calls == ["game_rotation"]
    assert report["status"] == "complete"


def test_missing_corrupted_and_tampered_files_are_refetched(tmp_path):
    run(tmp_path)
    directory = tmp_path / GAME
    (directory / "raw/box_score_usage_v3.json").write_text("{broken")
    (directory / "profiles/2.json").unlink()
    path = directory / "raw/box_score_scoring_v3.json"
    modified = json.loads(path.read_text())
    modified["unknownTopLevel"] = ["manually changed"]
    path.write_text(json.dumps(modified))
    report, transport = run(tmp_path)
    assert transport.calls == [
        "box_score_scoring_v3",
        "box_score_usage_v3",
        "common_player_info:2",
    ]
    assert report["status"] == "complete"


def test_in_progress_and_first_final_run_refresh_all_game_resources(tmp_path):
    run(tmp_path, FakeTransport(status=2))
    report, transport = run(tmp_path, FakeTransport(status=3))
    assert transport.calls == [r.name for r in RESOURCES]
    assert report["game_status"] == 3
    _, transport = run(tmp_path)
    assert not transport.calls


def test_interruption_during_final_refresh_does_not_freeze_live_data(tmp_path):
    run(tmp_path, FakeTransport(status=2))
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, FakeTransport(status=3, interrupt="box_score_advanced_v3"))
    report, transport = run(tmp_path)
    assert report["status"] == "complete"
    assert "box_score_usage_v3" in transport.calls
    assert "box_score_summary_v3" not in transport.calls
    raw = json.loads((tmp_path / GAME / "raw/box_score_usage_v3.json").read_text())
    assert raw == payload(BY_NAME["box_score_usage_v3"])


def test_force_refresh_includes_all_profiles_and_preserves_old_file_on_failure(
    tmp_path,
):
    run(tmp_path)
    path = tmp_path / GAME / "raw/box_score_advanced_v3.json"
    before = path.read_bytes()
    report, transport = run(
        tmp_path, FakeTransport(failures=("box_score_advanced_v3",)), force=True
    )
    assert len(transport.calls) == 16
    assert report["status"] == "partial"
    assert path.read_bytes() == before
    assert "retained_previous_file" in report["resources"]["box_score_advanced_v3"]
    _, transport = run(tmp_path)
    assert transport.calls == ["box_score_advanced_v3"]


def test_failed_forced_profile_refresh_is_retried_instead_of_using_old_profile(
    tmp_path,
):
    run(tmp_path)
    report, _ = run(
        tmp_path, FakeTransport(failures=("common_player_info:2",)), force=True
    )
    assert report["status"] == "partial"
    assert (tmp_path / GAME / "profiles/2.json").is_file()
    report, transport = run(tmp_path)
    assert transport.calls == ["common_player_info:2"]
    assert report["status"] == "complete"


def test_invalid_roster_id_does_not_prevent_other_profiles(tmp_path):
    traditional = payload(RESOURCES[1])
    traditional["boxScoreTraditional"]["homeTeam"]["players"].append(
        {"personId": "invalid"}
    )
    report, _ = run(
        tmp_path, FakeTransport(overrides={"box_score_traditional_v3": traditional})
    )
    assert report["profiles"]["person_ids"] == [1, 2, 3]
    assert report["summary"]["profiles_succeeded"] == 3
    assert not report["profiles"]["roster_complete"]
    assert report["status"] == "partial"


def test_endpoint_parameter_failure_does_not_stop_other_endpoints(
    tmp_path, monkeypatch
):
    from nba_pbp.game.resources import Resource

    original = Resource.request

    def build(self, game_id):
        if self.name == "box_score_advanced_v3":
            raise KeyError("upstream parameter change")
        return original(self, game_id)

    monkeypatch.setattr(Resource, "request", build)
    report, transport = run(tmp_path)
    assert report["resources"]["box_score_advanced_v3"]["status"] == "failed"
    assert "box_score_matchups_v3" in transport.calls
    assert report["summary"]["profiles_succeeded"] == 3


def test_session_setup_failure_still_writes_missing_resource_report(tmp_path):
    class FailedSetup(FakeTransport):
        def __enter__(self):
            raise requests.ConnectionError("secret proxy URL")

    report, _ = run(tmp_path, FailedSetup())
    assert report["status"] == "partial"
    assert len(report["summary"]["failed_resources"]) == 13
    assert "secret" not in json.dumps(report)
    assert (tmp_path / GAME / "manifest.json").is_file()


def test_echoed_game_id_mismatch_is_rejected_even_for_empty_shots():
    raw = {
        "parameters": {"GameID": "0022300002"},
        "resultSets": [dataset("Shot_Chart_Detail", ["GAME_ID"], [])],
    }
    with pytest.raises(ResponseValidationError):
        inspect_response(BY_NAME["shot_chart_detail"], raw, GAME)


def test_wrong_game_or_person_is_not_saved_as_success(tmp_path):
    advanced = payload(BY_NAME["box_score_advanced_v3"])
    advanced["boxScoreAdvanced"]["gameId"] = "0022300002"
    report, _ = run(
        tmp_path,
        FakeTransport(
            overrides={
                "box_score_advanced_v3": advanced,
                "common_player_info:3": payload(PROFILE, person_id=999),
            }
        ),
    )
    assert report["resources"]["box_score_advanced_v3"]["status"] == "failed"
    assert report["resources"]["common_player_info:3"]["status"] == "failed"
    assert not (tmp_path / GAME / "profiles/3.json").exists()
    shots = payload(BY_NAME["shot_chart_detail"])
    shots["resultSets"][0]["rowSet"][0][0] = "0022300002"
    with pytest.raises(ResponseValidationError):
        inspect_response(BY_NAME["shot_chart_detail"], shots, GAME)


def test_atomic_failure_preserves_old_json_and_cleans_temporary_file(
    tmp_path, monkeypatch
):
    target = tmp_path / "raw.json"
    atomic_json(target, {"old": True})
    before = target.read_bytes()

    def failed_replace(*args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(StorageError):
        atomic_json(target, {"new": True})
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize(
    "game_id", ["123", "００２２３００００１", "002230000x", "0022300001 "]
)
def test_cli_rejects_invalid_id_before_io(tmp_path, game_id):
    with pytest.raises(SystemExit) as exc:
        cli.main([game_id, "--output-dir", str(tmp_path)])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_cli_default_timeout_path_and_exit_codes(tmp_path, monkeypatch):
    args = cli.build_parser().parse_args([GAME])
    assert args.timeout == 30
    assert args.output_dir == Path(__file__).resolve().parents[1] / "data/output"

    class FakeCollector(Collector):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = FakeTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(cli, "Collector", FakeCollector)
    assert cli.main([GAME, "--output-dir", str(tmp_path)]) == 0

    class PartialCollector(FakeCollector):
        def run(self):
            self.transport.failures.add("box_score_usage_v3")
            self.force = True
            return super().run()

    monkeypatch.setattr(cli, "Collector", PartialCollector)
    assert cli.main([GAME, "--output-dir", str(tmp_path)]) == 1


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_transport_retries_paces_and_never_runs_dataframe_parser(monkeypatch):
    from nba_api.stats.endpoints.boxscoreadvancedv3 import BoxScoreAdvancedV3
    from nba_api.stats.library.http import NBAStatsHTTP

    clock = FakeClock()
    starts = []

    def send(self, **kwargs):
        starts.append(clock.now)
        if len(starts) == 1:
            raise requests.Timeout("secret proxy URL must not escape")

        class RawResponse:
            def get_dict(self):
                return payload(BY_NAME["box_score_advanced_v3"])

        return RawResponse()

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", send)

    def parse_forbidden(self):
        raise AssertionError("Raw-only archive must not run parsers")

    monkeypatch.setattr(BoxScoreAdvancedV3, "load_response", parse_forbidden)
    transport = Transport(sleep=clock.sleep, monotonic=clock.time, jitter=lambda *_: 0)
    result = transport.fetch(BY_NAME["box_score_advanced_v3"], GAME)
    assert result.attempts == 2
    transport.fetch(BY_NAME["box_score_advanced_v3"], GAME)
    assert all(b - a >= 1 for a, b in pairwise(starts))


@pytest.mark.parametrize("kind", ["403", "html", "429", "timeout", "json"])
def test_transport_error_policy_and_redaction(monkeypatch, kind):
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_pbp.common.errors import SourceBlockedError

    clock, calls = FakeClock(), []

    def failed(self, **kwargs):
        calls.append(kwargs)
        if kind in ("403", "429"):
            response = requests.Response()
            response.status_code = int(kind)
            raise requests.HTTPError(
                "http://user:password@proxy:8080", response=response
            )
        if kind == "html":
            raise SourceBlockedError("HTML")
        if kind == "json":
            raise json.JSONDecodeError("secret", "", 0)
        raise requests.Timeout("password")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", failed)
    transport = Transport(
        proxy="http://user:password@proxy:8080",
        sleep=clock.sleep,
        monotonic=clock.time,
        jitter=lambda *_: 0,
    )
    with pytest.raises(RequestFailure) as exc:
        transport.fetch(RESOURCES[0], GAME)
    assert len(calls) == (1 if kind in ("403", "html") else 2)
    assert "password" not in str(exc.value)


def test_shared_http_session_is_restored_after_exception():
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    old_stats, old_live = NBAStatsHTTP.get_session(), NBALiveHTTP.get_session()
    with pytest.raises(RuntimeError), Transport():
        assert NBAStatsHTTP.get_session() is NBALiveHTTP.get_session()
        raise RuntimeError("test")
    assert NBAStatsHTTP.get_session() is old_stats
    assert NBALiveHTTP.get_session() is old_live


def test_html_200_error_is_not_reported_as_proven_ip_block(monkeypatch):
    from curl_cffi import requests as curl_requests

    from nba_pbp.common.errors import SourceBlockedError
    from nba_pbp.common.http import StatusAwareBrowserSession, classify_error

    class ErrorPage:
        def __init__(self):
            self.headers = {"content-type": "text/html"}
            self.text = "<!DOCTYPE html><html>We are unable to process your request at the moment</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        curl_requests.Session, "get", lambda *args, **kwargs: ErrorPage()
    )
    session = StatusAwareBrowserSession()
    try:
        with pytest.raises(SourceBlockedError) as exc:
            session.get("https://stats.nba.com/stats/boxscoresummaryv3")
    finally:
        session.close()
    disposition = classify_error(exc.value)
    assert "尚不能确定原因" in disposition.reason
    assert "拦截了当前网络出口" not in disposition.reason
    assert disposition.fallback_allowed
    assert not disposition.retryable


def test_html_error_records_safe_http_diagnostics(monkeypatch):
    from curl_cffi import requests as curl_requests

    from nba_pbp.common.errors import SourceBlockedError
    from nba_pbp.common.http import StatusAwareBrowserSession, classify_error

    class ErrorPage:
        status_code = 200
        headers = {"content-type": "text/html", "server": "AkamaiNetStorage"}
        text = "<html>secret reflected URL or proxy credentials</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(curl_requests.Session, "get", lambda *a, **kw: ErrorPage())
    session = StatusAwareBrowserSession()
    try:
        with pytest.raises(SourceBlockedError) as exc:
            session.get("https://stats.nba.com/stats/commonplayerinfo")
    finally:
        session.close()
    reason = classify_error(exc.value).reason
    assert "HTTP 200" in reason and "AkamaiNetStorage" in reason
    assert "secret" not in reason and "credentials" not in reason


def test_stats_outage_skips_requests_but_keeps_cdn_and_resets_next_run(monkeypatch):
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_pbp.common.errors import SourceBlockedError
    from nba_pbp.game.resources import LIVE_BOX

    calls = []

    def blocked(self, **kwargs):
        calls.append(kwargs["endpoint"])
        raise SourceBlockedError("HTML", status_code=200, akamai=True)

    class LiveResponse:
        def get_dict(self):
            return payload(LIVE_BOX)

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", blocked)
    monkeypatch.setattr(
        NBALiveHTTP, "send_api_request", lambda *a, **kw: LiveResponse()
    )
    clock = FakeClock()
    transport = Transport(sleep=clock.sleep, monotonic=clock.time)
    with transport:
        for resource in RESOURCES[:2]:
            with pytest.raises(RequestFailure) as exc:
                transport.fetch(resource, GAME)
            assert exc.value.attempts == 1 and not exc.value.skipped
        for resource, person_id in ((RESOURCES[2], None), (PROFILE, 123)):
            with pytest.raises(RequestFailure) as exc:
                transport.fetch(resource, GAME, person_id)
            assert exc.value.attempts == 0 and exc.value.skipped
            assert "两个不同接口" in str(exc.value)
        assert transport.fetch(LIVE_BOX, GAME).raw == payload(LIVE_BOX)
    assert calls == [r.module for r in RESOURCES[:2]]
    # The next run must test the route again after a node change or recovery.
    with transport:
        with pytest.raises(RequestFailure) as exc:
            transport.fetch(RESOURCES[0], GAME)
        assert exc.value.attempts == 1 and not exc.value.skipped
    assert len(calls) == 3


def test_single_html_failure_does_not_disable_unrelated_stats_endpoints(monkeypatch):
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_pbp.common.errors import SourceBlockedError

    clock, calls = FakeClock(), []

    class RawResponse:
        def get_dict(self):
            return {"ok": True}

    def send(self, **kwargs):
        calls.append(kwargs["endpoint"])
        if len(calls) in (1, 2, 4):
            raise SourceBlockedError("HTML")
        return RawResponse()

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", send)
    transport = Transport(sleep=clock.sleep, monotonic=clock.time)
    # Two failures of the same endpoint don't establish a source-wide outage.
    for _ in range(2):
        with pytest.raises(RequestFailure):
            transport.fetch(RESOURCES[0], GAME)
    assert transport.fetch(RESOURCES[1], GAME).raw == {"ok": True}
    # A success resets the failure sequence.
    with pytest.raises(RequestFailure):
        transport.fetch(RESOURCES[2], GAME)
    assert transport.fetch(RESOURCES[3], GAME).raw == {"ok": True}
    assert len(calls) == 5


def test_outage_manifest_records_unrequested_resources_honestly(tmp_path, monkeypatch):
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_pbp.common.errors import SourceBlockedError

    def blocked(*args, **kwargs):
        raise SourceBlockedError("HTML")

    def live(self, **kwargs):
        from nba_pbp.game.resources import LIVE_BOX, LIVE_PBP

        resource = LIVE_BOX if kwargs["endpoint"].startswith("boxscore/") else LIVE_PBP

        class RawResponse:
            def get_dict(self):
                return payload(resource)

        return RawResponse()

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", blocked)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", live)
    clock = FakeClock()
    messages = []
    report = Collector(
        GAME,
        tmp_path,
        transport=Transport(sleep=clock.sleep, monotonic=clock.time),
        progress=messages.append,
    ).run()
    entries = report["resources"]
    assert report["status"] == "partial" and report["stats_unavailable"]
    assert report["summary"]["game_resources_succeeded"] == 0
    assert entries["live_box_score"]["status"] == "success"
    assert entries["live_play_by_play"]["status"] == "success"
    assert entries["box_score_summary_v3"]["attempts"] == 1
    assert entries["common_player_info:1"]["skipped"]
    assert entries["common_player_info:1"]["attempts"] == 0
    assert not (tmp_path / GAME / "profiles/1.json").exists()
    assert not any("正在抓取：common_player_info" in text for text in messages)
    assert sum("两个不同接口" in text for text in messages) == 1


def test_network_check_validates_both_sources_without_modifying_archive(
    tmp_path, monkeypatch, capsys
):
    from nba_pbp.game import diagnostics

    monkeypatch.setattr(diagnostics, "Transport", lambda *a: FakeTransport())
    assert cli.main([GAME, "--output-dir", str(tmp_path), "--check-network"]) == 0
    assert not list(tmp_path.iterdir())
    output = capsys.readouterr().out
    assert "NBA Stats：可用" in output and "NBA Live CDN：可用" in output
    monkeypatch.setattr(
        diagnostics,
        "Transport",
        lambda *a: FakeTransport(failures=("box_score_summary_v3",)),
    )
    assert cli.main([GAME, "--output-dir", str(tmp_path), "--check-network"]) == 1
    assert not list(tmp_path.iterdir())
    output = capsys.readouterr().out
    assert "NBA Stats：不可用" in output and "NBA Live CDN：可用" in output


def test_legacy_pbp_live_fallback_uses_real_live_dataset_and_saves_all_fields(
    tmp_path, monkeypatch
):
    from nba_api.library.http import NBAResponse
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_pbp.common.errors import SourceBlockedError
    from nba_pbp.pbp import cli as pbp_cli

    raw = {
        "meta": {"version": 1},
        "game": {
            "gameId": GAME,
            "actions": [
                {
                    "actionNumber": 2,
                    "clock": "PT12M00.00S",
                    "description": "Period Start",
                    "x": None,
                    "unknown": {"keep": [1, 2]},
                },
                {
                    "actionNumber": 7,
                    "clock": "PT11M39.00S",
                    "description": "original shot description",
                    "x": 14.4,
                    "shotDistance": 8.58,
                },
            ],
        },
    }
    calls = []

    def stats_unavailable(self, **kwargs):
        calls.append("stats")
        raise SourceBlockedError("HTML", status_code=200)

    def live_response(self, **kwargs):
        calls.append("cdn")
        return NBAResponse(json.dumps(raw), 200, "https://cdn.nba.com/example.json")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", stats_unavailable)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", live_response)
    assert pbp_cli.main([GAME, "--output-dir", str(tmp_path)]) == 0
    directory = tmp_path / GAME / "pbp"
    assert json.loads((directory / "api_response_raw.json").read_text()) == raw
    rows = json.loads((directory / "play_by_play_raw.json").read_text())
    assert rows == [{"gameId": GAME, **row} for row in raw["game"]["actions"]]
    assert (directory / "play_by_play_raw.csv").is_file()
    assert calls == ["stats", "cdn"]
    # A subsequent normal run must validate and use these outputs as a cache.
    assert pbp_cli.main([GAME, "--output-dir", str(tmp_path)]) == 0
    assert calls == ["stats", "cdn"]
