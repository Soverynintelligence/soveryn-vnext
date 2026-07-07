"""Template-presence tests for the Scotty Approvals tile (Task 6).

TDD step 1: write the failing tests that describe what the template must contain.
Run with:
    ~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_command_center_delegation.py -q
"""


def _html(app_state):
    return app_state.get("/").get_data(as_text=True)


# ── Structural presence ────────────────────────────────────────────────────────

def test_scotty_approvals_panel_present(app_state):
    """The rendered page contains a .scotty-approvals section."""
    assert "scotty-approvals" in _html(app_state)


def test_render_scotty_approvals_js_hook(app_state):
    """The page defines a renderScottyApprovals JS function."""
    assert "renderScottyApprovals" in _html(app_state)


def test_delegation_pending_fetch(app_state):
    """The JS fetches /api/delegation/pending."""
    assert "/api/delegation/pending" in _html(app_state)


def test_cognition_panel_inside_twin_row(app_state):
    """The cognition panel sits inside a twin-column grid wrapper (cognition-approvals-row)."""
    html = _html(app_state)
    assert "cognition-approvals-row" in html
    # Both panels must appear inside the same wrapper — check ordering
    cog_pos = html.index("data-cognition-panel")
    row_start = html.index("cognition-approvals-row")
    scotty_pos = html.index("scotty-approvals")
    # cognition-panel appears after the row wrapper opens
    assert row_start < cog_pos
    # scotty-approvals appears after the row wrapper opens too
    assert row_start < scotty_pos


def test_approve_reject_buttons_present(app_state):
    """The Scotty approvals JS renders Approve and Reject buttons."""
    html = _html(app_state)
    assert "Approve" in html
    assert "Reject" in html


def test_approve_posts_to_delegation_route(app_state):
    """The approve action POSTs to /api/delegation/.../approve."""
    assert "/api/delegation/" in _html(app_state)
    assert "approve" in _html(app_state)
    assert "reject" in _html(app_state)


def test_scotty_approvals_in_refresh_cycle(app_state):
    """renderScottyApprovals is called inside refreshAll()."""
    html = _html(app_state)
    # Find refreshAll and make sure renderScottyApprovals comes between
    # the function definition and the closing brace
    refresh_pos = html.index("function refreshAll()")
    call_pos = html.index("renderScottyApprovals()", refresh_pos)
    # Should find the call within a reasonable range (before the next function)
    assert call_pos - refresh_pos < 2000
