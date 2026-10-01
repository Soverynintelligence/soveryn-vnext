"""Shim — implementation lives in portable acttruth package."""
from acttruth.lessons import *  # noqa: F403
from acttruth.lessons import (
    DEFAULT_LOOKBACK,
    DEFAULT_STREAK,
    DEFAULT_WINDOW_HOURS,
    Lesson,
    classify_error,
    lessons_brief,
    lessons_from_events,
    maybe_lesson_for_tool_result,
    pattern_key,
)

# Re-export house get_acttruth name for tests that patch this module attribute.
from soveryn.platform.acttruth.hooks import get_acttruth  # noqa: F401
