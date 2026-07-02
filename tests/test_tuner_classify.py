from soveryn.platform.tuner.result import RunOutcome, classify, is_degenerate

def _oc(**kw):
    base = dict(listened=False, exit_code=1, stderr="", generated_tokens=0,
                output_text="", gpu_faulted=False)
    base.update(kw); return RunOutcome(**base)

def test_oom_from_real_235b_string():
    s = "ggml_backend_cuda_buffer_type_alloc_buffer: allocating 44148 MiB on device 2: cudaMalloc failed: out of memory"
    assert classify(_oc(stderr=s))[0] == "oom"

def test_load_failed_cuda_compat_miss():
    s = "ggml_cuda_init: failed to initialize CUDA: CUDA driver version is insufficient for CUDA runtime version"
    assert classify(_oc(stderr=s))[0] == "load_failed"

def test_load_failed_bad_arg():
    s = "error while handling argument \"-fa\": error: unknown value for --flash-attn: '--host'"
    assert classify(_oc(stderr=s))[0] == "load_failed"

def test_hardware_error_takes_priority():
    s = "CUDA error: an illegal memory access was encountered\ncudaMalloc failed: out of memory"
    assert classify(_oc(stderr=s))[0] == "hardware_error"

def test_hardware_error_fallen_off_bus():
    assert classify(_oc(stderr="GPU 2 has fallen off the bus"))[0] == "hardware_error"

def test_hardware_error_from_gpu_faulted_flag():
    assert classify(_oc(gpu_faulted=True, stderr="anything"))[0] == "hardware_error"

def test_hung_listened_but_no_tokens():
    assert classify(_oc(listened=True, exit_code=None, generated_tokens=0))[0] == "hung"

def test_hung_never_listened_no_error():
    assert classify(_oc(listened=False, exit_code=None, stderr="loading model..."))[0] == "hung"

def test_garbage_degenerate_repetition():
    out = "the the the the the the the the the the the the"
    assert classify(_oc(listened=True, generated_tokens=12, output_text=out))[0] == "garbage"

def test_garbage_empty_output():
    assert classify(_oc(listened=True, generated_tokens=5, output_text="   "))[0] == "garbage"

def test_ok_clean_run():
    out = "Paris is the capital of France."
    assert classify(_oc(listened=True, exit_code=None, generated_tokens=7, output_text=out))[0] == "ok"

def test_is_degenerate_helper():
    assert is_degenerate("")
    assert is_degenerate("ok ok ok ok ok ok ok ok")
    assert not is_degenerate("A clear, varied sentence with real content.")
