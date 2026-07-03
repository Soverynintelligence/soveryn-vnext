from soveryn.platform.tuner.candidate import Candidate, to_llama_server_args

def _cand(**kw):
    base = dict(model_file="/m/x.gguf", device_map="CUDA0,CUDA2", tensor_split="85,15",
               ngl=99, ot_offload=None, ctx_size=8192, cache_type_k="q8_0",
               cache_type_v="q8_0", flash_attn=True)
    base.update(kw); return Candidate(**base)

def test_full_candidate_maps_to_flags():
    args = to_llama_server_args(_cand(), host="127.0.0.1", port=8199)
    assert "-m" in args and "/m/x.gguf" in args
    assert "--tensor-split" in args and "85,15" in args
    assert "-ngl" in args and "99" in args
    assert "--cache-type-k" in args and "--cache-type-v" in args
    assert "-fa" in args and args[args.index("-fa")+1] == "on"
    assert "--port" in args and "8199" in args

def test_optional_fields_omitted_when_none():
    args = to_llama_server_args(_cand(tensor_split=None, ot_offload=None), host="127.0.0.1", port=1)
    assert "--tensor-split" not in args
    assert "-ot" not in args

def test_expert_offload_flag():
    args = to_llama_server_args(_cand(ot_offload="exps=CPU"), host="127.0.0.1", port=1)
    assert "-ot" in args and args[args.index("-ot")+1] == "exps=CPU"

def test_flash_attn_off_is_explicit():
    args = to_llama_server_args(_cand(flash_attn=False), host="127.0.0.1", port=1)
    assert args[args.index("-fa")+1] == "off"


def test_candidate_backend_defaults_to_cuda():
    from soveryn.platform.tuner.candidate import Candidate
    c = Candidate(
        model_file="/m.gguf", device_map="CUDA0", ngl=99, ctx_size=4096,
        cache_type_k="f16", cache_type_v="f16", flash_attn=True,
    )
    assert c.backend == "cuda"


def test_resolve_binary_known_and_unknown():
    from soveryn.platform.tuner.measure import _resolve_binary
    assert _resolve_binary("cuda").endswith("llama-server")
    import pytest
    with pytest.raises(ValueError):
        _resolve_binary("vulkan")
