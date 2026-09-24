"""Shim — implementation lives in portable acttruth package."""
from acttruth.earned_keep import *  # noqa: F403
from acttruth.earned_keep import EarnedKeepScore, record_earned_keep, score_unprompted_act
from soveryn.platform.acttruth.hooks import get_acttruth  # noqa: F401
