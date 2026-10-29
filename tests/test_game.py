from __future__ import annotations

import copy
import json
import os
from itertools import pairwise
from pathlib import Path
from typing import ClassVar

import pytest
import requests

from nba_game import cli
from nba_game.collector import Collector
from nba_game.errors import ResponseValidationError, StorageError
from nba_game.sources.live import LIVE_BOX, LIVE_PBP
from nba_game.sources.stats import (
    BY_NAME,
    LINEUP_SHOTS,
    LINEUPS,
    PROFILE,
    RESOURCES,
    game_season,
)
from nba_game.storage import atomic_json
from nba_game.transport import RequestFailure, Response, Transport
from nba_game.validation import KEY_FIELDS, inspect_response

GAME = "0022300001"


def game_keys():
    return (
        [r.name for r in RESOURCES[:2]]
        + [LIVE_BOX.name, LIVE_PBP.name]
        + [r.name for r in RESOURCES[2:]]
        + [
            resource.key()
            for tid in (10, 20)
            for resource in (LINEUPS.bind(tid), LINEUP_SHOTS.bind(tid, "-1-2-3-4-5-"))
        ]
    )


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
    if resource.module == "dunkscoreleaders":
        return {"params": {"GameID": GAME}, "dunks": [{"gameId": GAME, "eventNum": 1}]}
    if resource.module == "teamdashlineups":
        return {
            "parameters": {"GameID": GAME, "TeamID": resource.team_id},
            "resultSets": [
                dataset("Overall", ["TEAM_ID", "GP"], [[resource.team_id, 1]]),
                dataset("Lineups", ["GP", "GROUP_ID"], [[1, "-1-2-3-4-5-"]]),
            ],
        }
    if resource.module == "shotchartlineupdetail":
        return {
            "resultSets": [
                dataset(
                    "ShotChartLineupDetail",
                    ["GAME_ID", "TEAM_ID", "GROUP_ID"],
                    [[GAME, resource.team_id, resource.group_id]],
                )
            ]
        }
    if resource.root:
        root = {"gameId": GAME, "unknown": {"nested": [1, None, "原始"]}}
        if resource.name in ("play_by_play_v3", "live_play_by_play"):
            root["actions"] = [
                {
                    "actionNumber": 1,
                    "description": "keep unchanged",
                    "unknown": [3, 4],
                    "scoreHome": "100",
                    "scoreAway": "98",
                }
            ]
        else:
            root["homeTeam"] = {
                "players": [{"personId": 1}],
                "statistics": {"points": 100, "fieldGoalsAttempted": 1},
                "teamId": 10,
                "score": 100,
            }
            root["awayTeam"] = {
                "players": [{"personId": 2}],
                "statistics": {"points": 98, "fieldGoalsAttempted": 1},
                "teamId": 20,
                "score": 98,
            }
            for side in ("homeTeam", "awayTeam"):
                root[side]["players"][0]["statistics"] = {
                    key: 0 for key in KEY_FIELDS.get(resource.name, ())
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
        key = resource.key(person_id)
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
    assert len(RESOURCES) == len({r.module for r in RESOURCES}) == 15
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
    assert report["summary"]["game_resources_succeeded"] == len(game_keys())
    assert report["profiles"]["person_ids"] == [1, 2, 3]
    assert transport.calls == game_keys() + [
        f"common_player_info:{i}" for i in (1, 2, 3)
    ]
    directory = tmp_path / GAME
    files = [p for p in directory.rglob("*") if p.is_file()]
    assert len(files) == len(game_keys()) + 5
    assert all(p.suffix in (".json", ".md") for p in files)
    assert json.loads(
        (directory / "raw/stats/box_score_traditional_v3.json").read_text(encoding="utf-8")
    ) == payload(RESOURCES[1])
    assert json.loads((directory / "raw/players/1.json").read_text(encoding="utf-8")) == payload(
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
    assert (tmp_path / GAME / "raw/live/live_box_score.json").is_file()


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
    assert report["status"] == "partial"
    assert report["summary"]["failed_checks"] == ["shotchart_matches_boxscore_fga"]
    assert set(report["summary"]["empty_resources"]) == {
        "shot_chart_detail",
        "game_rotation",
    }
    assert (
        json.loads((tmp_path / GAME / "raw/stats/shot_chart_detail.json").read_text(encoding="utf-8"))
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
    (directory / "raw/stats/box_score_usage_v3.json").write_text("{broken", encoding="utf-8")
    (directory / "raw/players/2.json").unlink()
    path = directory / "raw/stats/box_score_scoring_v3.json"
    modified = json.loads(path.read_text(encoding="utf-8"))
    modified["unknownTopLevel"] = ["manually changed"]
    path.write_text(json.dumps(modified), encoding="utf-8")
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
    assert transport.calls == game_keys()
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
    raw = json.loads(
        (tmp_path / GAME / "raw/stats/box_score_usage_v3.json").read_text(encoding="utf-8")
    )
    assert raw == payload(BY_NAME["box_score_usage_v3"])


def test_force_refresh_includes_all_profiles_and_preserves_old_file_on_failure(
    tmp_path,
):
    run(tmp_path)
    path = tmp_path / GAME / "raw/stats/box_score_advanced_v3.json"
    before = path.read_bytes()
    report, transport = run(
        tmp_path, FakeTransport(failures=("box_score_advanced_v3",)), force=True
    )
    assert len(transport.calls) == len(game_keys()) + 3
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
    assert (tmp_path / GAME / "raw/players/2.json").is_file()
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


@pytest.mark.parametrize("side", ["homeTeam", "awayTeam"])
@pytest.mark.parametrize(
    ("resource", "field"), [(RESOURCES[0], "inactives"), (RESOURCES[1], "players")]
)
def test_missing_roster_field_is_failed_and_retried(tmp_path, resource, field, side):
    raw = payload(resource)
    del raw[resource.root][side][field]
    report, transport = run(
        tmp_path, FakeTransport(overrides={resource.name: raw})
    )
    assert report["status"] == "partial"
    assert not report["profiles"]["roster_complete"]
    assert report["resources"][resource.name]["status"] == "failed"
    assert report["summary"]["profiles_succeeded"] == (2 if resource is RESOURCES[0] else 3)
    assert "box_score_defensive_v2" in transport.calls
    assert not (tmp_path / GAME / resource.relative_path()).exists()

    report, transport = run(tmp_path)
    # Without a summary, the first traditional response predates final-status
    # confirmation, and inactive player 3 is unknown until the retry.
    expected = (
        [RESOURCES[0].name, RESOURCES[1].name, PROFILE.key(3)]
        if resource is RESOURCES[0]
        else [resource.name]
    )
    assert transport.calls == expected
    assert report["status"] == "complete"


def test_explicit_empty_inactive_lists_are_complete(tmp_path):
    raw = payload(RESOURCES[0])
    for side in ("homeTeam", "awayTeam"):
        raw[RESOURCES[0].root][side]["inactives"] = []
    report, _ = run(tmp_path, FakeTransport(overrides={RESOURCES[0].name: raw}))
    assert report["status"] == "complete"
    assert report["profiles"]["roster_complete"]
    assert report["profiles"]["person_ids"] == [1, 2]


@pytest.mark.parametrize("side", ["homeTeam", "awayTeam"])
def test_one_sided_traditional_roster_is_incomplete(tmp_path, side):
    raw = payload(RESOURCES[1])
    raw[RESOURCES[1].root][side]["players"] = []
    report, _ = run(tmp_path, FakeTransport(overrides={RESOURCES[1].name: raw}))
    assert report["status"] == "partial"
    assert not report["profiles"]["roster_complete"]
    assert report["profiles"]["person_ids"] == [1, 2, 3]
    assert report["summary"]["profiles_succeeded"] == 3


@pytest.mark.parametrize("side", ["homeTeam", "awayTeam"])
def test_live_boxscore_requires_explicit_player_lists(side):
    raw = payload(LIVE_BOX)
    del raw[LIVE_BOX.root][side]["players"]
    with pytest.raises(ResponseValidationError):
        inspect_response(LIVE_BOX, raw, GAME)


@pytest.mark.parametrize(
    "kind", ["duplicate_dataset", "duplicate_header", "non_string_header"]
)
def test_ambiguous_result_sets_are_rejected_without_replacing_old_cache(tmp_path, kind):
    resource = BY_NAME["shot_chart_detail"]
    run(tmp_path)
    path = tmp_path / GAME / resource.relative_path()
    before = path.read_bytes()
    raw = payload(resource)
    if kind == "duplicate_dataset":
        wrong = copy.deepcopy(raw["resultSets"][0])
        wrong["rowSet"][0][0] = "0022300002"
        raw["resultSets"].insert(0, wrong)
    elif kind == "duplicate_header":
        raw["resultSets"][0]["headers"][1] = "GAME_ID"
        raw["resultSets"][0]["rowSet"] = [[GAME, "0022300002"]]
    else:
        raw["resultSets"][0]["headers"][1] = {"invalid": "header"}
    with pytest.raises(ResponseValidationError):
        inspect_response(resource, raw, GAME)
    report, _ = run(tmp_path, FakeTransport(overrides={resource.name: raw}), force=True)
    entry = report["resources"][resource.name]
    assert report["status"] == "partial"
    assert entry["status"] == "failed"
    assert entry["retained_previous_file"] == str(resource.relative_path())
    assert path.read_bytes() == before


def test_endpoint_parameter_failure_does_not_stop_other_endpoints(
    tmp_path, monkeypatch
):
    from nba_game.sources.stats import Resource

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
    assert len(report["summary"]["failed_resources"]) == len(RESOURCES) + 4
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
    assert not (tmp_path / GAME / "raw/players/3.json").exists()
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
    assert args.output_dir == Path(__file__).resolve().parents[1] / "data/games"

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


@pytest.mark.parametrize(
    "kind", ["400", "403", "500", "html", "429", "timeout", "json"]
)
def test_transport_error_policy_and_redaction(monkeypatch, kind):
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_game.errors import SourceBlockedError

    clock, calls = FakeClock(), []

    def failed(self, **kwargs):
        calls.append(kwargs)
        if kind in ("400", "403", "429", "500"):
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
    assert len(calls) == (1 if kind in ("400", "403", "html") else 2)
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

    from nba_game.errors import SourceBlockedError
    from nba_game.transport import StatusAwareBrowserSession, classify_error

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

    from nba_game.errors import SourceBlockedError
    from nba_game.transport import StatusAwareBrowserSession, classify_error

    class ErrorPage:
        status_code = 200
        headers: ClassVar[dict] = {
            "content-type": "text/html",
            "server": "AkamaiNetStorage",
        }
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

    from nba_game.errors import SourceBlockedError
    from nba_game.sources.live import LIVE_BOX

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

    from nba_game.errors import SourceBlockedError

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


@pytest.mark.parametrize("failure", ["timeout", "http_403", "invalid_json"])
def test_non_html_stats_error_breaks_html_failure_sequence(monkeypatch, failure):
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_game.errors import SourceBlockedError

    calls = []

    class RawResponse:
        def get_dict(self):
            return {"ok": True}

    def send(self, **kwargs):
        endpoint = kwargs["endpoint"]
        calls.append(endpoint)
        if endpoint in (RESOURCES[0].module, RESOURCES[2].module):
            raise SourceBlockedError("HTML")
        if endpoint == RESOURCES[1].module:
            if failure == "timeout":
                raise requests.Timeout("sensitive proxy details")
            if failure == "http_403":
                response = requests.Response()
                response.status_code = 403
                raise requests.HTTPError(response=response)
            raise json.JSONDecodeError("invalid JSON", "", 0)
        return RawResponse()

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", send)
    clock = FakeClock()
    with Transport(sleep=clock.sleep, monotonic=clock.time) as transport:
        for resource in RESOURCES[:3]:
            with pytest.raises(RequestFailure) as exc:
                transport.fetch(resource, GAME)
            assert not exc.value.skipped
            assert not transport.stats_paused
        assert transport.fetch(RESOURCES[3], GAME).raw == {"ok": True}
    assert calls.count(RESOURCES[1].module) == (1 if failure == "http_403" else 2)
    assert calls[-1] == RESOURCES[3].module


def test_outage_manifest_records_unrequested_resources_honestly(tmp_path, monkeypatch):
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    from nba_game.errors import SourceBlockedError

    def blocked(*args, **kwargs):
        raise SourceBlockedError("HTML")

    def live(self, **kwargs):
        from nba_game.sources.live import LIVE_BOX, LIVE_PBP

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
    assert report["summary"]["game_resources_succeeded"] == 2
    assert entries["live_box_score"]["status"] == "success"
    assert entries["live_play_by_play"]["status"] == "success"
    assert entries["box_score_summary_v3"]["attempts"] == 1
    assert entries["common_player_info:1"]["skipped"]
    assert entries["common_player_info:1"]["attempts"] == 0
    assert not (tmp_path / GAME / "raw/players/1.json").exists()
    assert not any("正在抓取：common_player_info" in text for text in messages)
    assert sum("两个不同接口" in text for text in messages) == 1


def test_network_check_validates_both_sources_without_modifying_archive(
    tmp_path, monkeypatch, capsys
):
    from nba_game import diagnostics

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


def test_extension_parameters_are_game_scoped_and_omit_nulls():
    dunk = BY_NAME["dunk_score_leaders"].request("0042400401").parameters
    assert dunk["GameID"] == "0042400401"
    assert dunk["Season"] == "2024-25" and dunk["SeasonType"] == "Playoffs"
    assert dunk["LeagueID"] == "00"
    assert "PlayerID" not in dunk and "TeamID" not in dunk
    lineup = LINEUPS.bind(10).request(GAME).parameters
    assert lineup["TeamID"] == 10 and lineup["GroupQuantity"] == 5
    assert lineup["MeasureType"] == "Base" and lineup["PerMode"] == "Totals"
    shots = LINEUP_SHOTS.bind(10, "-1-2-3-4-5-").request(GAME).parameters
    assert shots["GROUP_ID"] == "-1-2-3-4-5-"
    assert shots["ContextMeasure"] == "FGA"
    assert shots["GameID"] == GAME and shots["Season"] == "2023-24"


def test_empty_dunks_are_legal_and_retried_on_next_run(tmp_path):
    empty = {"params": {"GameID": GAME}, "dunks": []}
    report, _ = run(tmp_path, FakeTransport(overrides={"dunk_score_leaders": empty}))
    assert report["status"] == "complete"
    assert report["summary"]["empty_resources"] == ["dunk_score_leaders"]
    second, transport = run(tmp_path)
    assert transport.calls == ["dunk_score_leaders"]
    assert second["status"] == "complete"


def test_lineup_failure_skips_only_its_dependents(tmp_path):
    report, transport = run(tmp_path, FakeTransport(failures=("team_dash_lineups:10",)))
    assert report["resources"]["shot_chart_lineup_detail:10"]["status"] == "skipped"
    assert report["resources"]["shot_chart_lineup_detail:10"]["attempts"] == 0
    assert "shot_chart_lineup_detail:20:-1-2-3-4-5-" in transport.calls
    assert report["summary"]["profiles_succeeded"] == 3
    assert report["status"] == "partial"
    report, transport = run(tmp_path)
    assert transport.calls == [
        "team_dash_lineups:10",
        "shot_chart_lineup_detail:10:-1-2-3-4-5-",
    ]
    assert report["status"] == "complete"


def test_missing_team_ids_record_dependency_and_still_collect_profiles(tmp_path):
    overrides = {}
    for resource in (RESOURCES[0], RESOURCES[1], LIVE_BOX):
        raw = payload(resource)
        for side in ("homeTeam", "awayTeam"):
            raw[resource.root][side].pop("teamId")
        overrides[resource.name] = raw
    report, transport = run(tmp_path, FakeTransport(overrides=overrides))
    assert report["resources"]["team_dash_lineups"]["status"] == "skipped"
    assert report["resources"]["shot_chart_lineup_detail"]["status"] == "skipped"
    assert report["summary"]["profiles_succeeded"] == 3
    assert "box_score_defensive_v2" in transport.calls


@pytest.mark.parametrize(
    "kind",
    ["wrong_game", "wrong_team", "wrong_group", "unsafe_group", "multiple_games"],
)
def test_lineup_and_dunk_identity_validation(kind):
    resource = (
        LINEUPS.bind(10)
        if kind in ("unsafe_group", "multiple_games")
        else LINEUP_SHOTS.bind(10, "-1-2-3-4-5-")
    )
    raw = payload(resource)
    if kind == "wrong_game":
        raw["resultSets"][0]["rowSet"][0][0] = "0022300002"
    elif kind == "wrong_team":
        raw["resultSets"][0]["rowSet"][0][1] = 999
    elif kind == "wrong_group":
        raw["resultSets"][0]["rowSet"][0][2] = "-1-2-3-4-6-"
    elif kind == "unsafe_group":
        raw["resultSets"][1]["rowSet"][0][1] = "../../escape"
    else:
        raw["resultSets"][0]["rowSet"][0][1] = 82
    with pytest.raises(ResponseValidationError):
        inspect_response(resource, raw, GAME)
    with pytest.raises(ResponseValidationError):
        inspect_response(
            BY_NAME["dunk_score_leaders"], {"dunks": [{"gameId": "0022300002"}]}, GAME
        )


def test_cross_source_score_disagreement_is_partial(tmp_path):
    live = payload(LIVE_BOX)
    live["game"]["homeTeam"]["score"] = 99
    report, _ = run(tmp_path, FakeTransport(overrides={LIVE_BOX.name: live}))
    assert report["status"] == "partial"
    assert report["summary"]["failed_resources"] == []
    assert "score:live_box_score:homeTeam" in report["summary"]["failed_checks"]
    assert (
        "score:live_box_score:homeTeam" in (tmp_path / GAME / "summary.md").read_text(encoding="utf-8")
    )


def legacy_archive(tmp_path):
    from nba_game.storage import file_hash

    legacy = tmp_path / "output" / GAME
    entries = {}
    for resource in RESOURCES[:13]:
        path = legacy / "raw" / f"{resource.name}.json"
        atomic_json(path, payload(resource))
        entries[resource.name] = {
            "status": "success",
            "sha256": file_hash(path),
            "parameters": {"GameID": GAME},
            "game_status_at_fetch": 3,
            "fetched_at": "2025-01-01T00:00:00+00:00",
        }
    path = legacy / "profiles/1.json"
    atomic_json(path, payload(PROFILE, person_id=1))
    entries["common_player_info:1"] = {
        "status": "success",
        "sha256": file_hash(path),
        "fetched_at": "2025-01-01T00:00:00+00:00",
    }
    atomic_json(
        legacy / "manifest.json",
        {"schema_version": 1, "game_id": GAME, "resources": entries},
    )
    return legacy


def test_legacy_copy_preserves_source_provenance_and_reuses_verified_cache(tmp_path):
    legacy = legacy_archive(tmp_path)
    before = {
        str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*.json")
    }
    report, transport = run(tmp_path / "games")
    assert report["status"] == "complete"
    assert all(r.name not in transport.calls for r in RESOURCES[:13])
    assert "common_player_info:1" not in transport.calls
    assert "box_score_defensive_v2" in transport.calls
    entry = report["resources"]["box_score_traditional_v3"]
    assert entry["fetched_at"] == "2025-01-01T00:00:00+00:00"
    assert Path(entry["migration"]["source_file"]) == (
        legacy / "raw/box_score_traditional_v3.json"
    ).resolve()
    assert before == {
        str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob("*.json")
    }
    assert report["schema_version"] == 2


def test_migration_rejects_corrupt_old_files_and_keeps_valid_new_files(tmp_path):
    legacy = legacy_archive(tmp_path)
    (legacy / "raw/box_score_usage_v3.json").write_text("{broken", encoding="utf-8")
    new_raw = payload(RESOURCES[1])
    new_raw["unknownTopLevel"] = ["newer version"]
    run(
        tmp_path / "games",
        FakeTransport(overrides={RESOURCES[1].name: new_raw}),
        force=True,
    )
    destination = tmp_path / "games" / GAME / RESOURCES[1].relative_path()
    before = destination.read_bytes()
    report, _ = run(tmp_path / "games")
    assert destination.read_bytes() == before
    assert report["status"] == "complete"
    destination = tmp_path / "other" / GAME
    from nba_game.storage import import_legacy

    import_legacy(destination, legacy, GAME)
    assert not (destination / BY_NAME["box_score_usage_v3"].relative_path()).exists()


def test_interruption_report_marks_unexecuted_profiles_and_preserves_progress(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, FakeTransport(interrupt="common_player_info:2"))
    report = json.loads((tmp_path / GAME / "manifest.json").read_text(encoding="utf-8"))
    assert report["status"] == "interrupted"
    assert report["resources"]["common_player_info:1"]["status"] == "success"
    assert report["resources"]["common_player_info:2"]["status"] == "skipped"
    assert (tmp_path / GAME / "summary.md").exists()
    report, transport = run(tmp_path)
    assert transport.calls == ["common_player_info:2", "common_player_info:3"]
    assert report["status"] == "complete"


def test_missing_required_statistics_is_a_reported_failure(tmp_path):
    advanced = payload(BY_NAME["box_score_advanced_v3"])
    advanced["boxScoreAdvanced"]["homeTeam"]["players"][0]["statistics"] = None
    report, _ = run(
        tmp_path, FakeTransport(overrides={"box_score_advanced_v3": advanced})
    )
    assert report["status"] == "partial"
    assert report["resources"]["box_score_advanced_v3"]["status"] == "failed"
    assert report["summary"]["profiles_succeeded"] == 3


def test_empty_statistics_fields_are_not_mistaken_for_complete_data(tmp_path):
    advanced = payload(BY_NAME["box_score_advanced_v3"])
    advanced["boxScoreAdvanced"]["homeTeam"]["players"][0]["statistics"] = {}
    report, _ = run(
        tmp_path, FakeTransport(overrides={"box_score_advanced_v3": advanced})
    )
    assert report["resources"]["box_score_advanced_v3"]["status"] == "success"
    assert report["status"] == "partial"
    assert report["summary"]["failed_checks"] == ["fields:box_score_advanced_v3"]


def test_corrupt_manifest_entries_do_not_break_migration_or_collection(tmp_path):
    legacy = legacy_archive(tmp_path)
    manifest = json.loads((legacy / "manifest.json").read_text(encoding="utf-8"))
    manifest["resources"]["box_score_summary_v3"] = None
    manifest["resources"]["box_score_traditional_v3"]["parameters"] = None
    atomic_json(legacy / "manifest.json", manifest)
    report, _ = run(tmp_path / "games")
    assert report["status"] == "complete"


def test_legacy_wrong_game_is_not_imported_even_with_matching_checksum(tmp_path):
    from nba_game.storage import file_hash, import_legacy

    legacy = legacy_archive(tmp_path)
    path = legacy / "raw/box_score_advanced_v3.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["boxScoreAdvanced"]["gameId"] = "0022300002"
    atomic_json(path, raw)
    manifest = json.loads((legacy / "manifest.json").read_text(encoding="utf-8"))
    manifest["resources"]["box_score_advanced_v3"]["sha256"] = file_hash(path)
    atomic_json(legacy / "manifest.json", manifest)
    dest = tmp_path / "games" / GAME
    import_legacy(dest, legacy, GAME)
    assert not (dest / BY_NAME["box_score_advanced_v3"].relative_path()).exists()
