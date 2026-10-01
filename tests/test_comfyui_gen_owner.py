"""generate_image can be owned by Eve as well as Aetheria."""

from soveryn.agents.aetheria.tools.comfyui_gen import (
    _build_workflow,
    build_generate_image_tool,
)


def test_build_generate_image_tool_eve_owner():
    tool = build_generate_image_tool(owner_agent="eve")
    assert tool.name == "generate_image"
    assert tool.owner == "eve"


def test_workflow_filename_prefix_follows_owner():
    wf = _build_workflow(
        checkpoint="x.safetensors",
        prompt="a pond",
        negative_prompt="",
        width=1024,
        height=1024,
        seed=1,
        steps=6,
        cfg=1.8,
        sampler_name="dpmpp_sde",
        scheduler="sgm_uniform",
        filename_prefix="eve",
    )
    assert wf["7"]["inputs"]["filename_prefix"] == "eve"
