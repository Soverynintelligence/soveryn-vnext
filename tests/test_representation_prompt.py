from soveryn.agents.representation.prompt import render_representation_prompt

def test_prompt_contains_contract():
    p = render_representation_prompt(subject="jon",
        briefing="[node:t1] jon: I want the honest read",
        prior_conclusions="[node:p1] Jon values directness")
    for s in ("jon", "deductive", "inductive", "abductive",
              "MODE | CONFIDENCE | CONTENT | [node:ID]", "[node:t1]", "[node:p1]"):
        assert s in p
