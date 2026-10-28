"""Both official Live feeds are always part of a game collection."""

from nba_game.models import Resource

LIVE_BOX = Resource("live_box_score", "live_boxscore", "BoxScore", "game")
LIVE_PBP = Resource("live_play_by_play", "live_playbyplay", "PlayByPlay", "game")
RESOURCES = (LIVE_BOX, LIVE_PBP)
