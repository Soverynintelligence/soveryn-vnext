from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.measure import measure

def _cand():
    return Candidate(model_file="/m/x.gguf", device_map="CUDA0", ngl=99,
        ctx_size=4096, cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True)

class FakeHandle:
    def __init__(self, *, listened, stderr="", tokens=0, out="", faulted=False, tok_s=0.0):
        self._l, self.stderr, self._t, self._o, self._f, self._toks = \
            listened, stderr, tokens, out, faulted, tok_s
        self.killed = False; self.vram_waited = False
    def wait_listen(self, timeout): return self._l
    def benchmark(self, prompt, timeout): return (self._t, self._o, self._toks)
    def peak_vram(self, devices): return {d: 100 for d in devices}
    def gpu_faulted(self): return self._f
    def kill(self): self.killed = True
    def wait_vram_released(self, devices, timeout): self.vram_waited = True; return True

def _launcher(handle):
    def make(binary, args, env): return handle
    return make

def test_measure_ok():
    h = FakeHandle(listened=True, tokens=7, out="Paris.", tok_s=14.2)
    m = measure(_cand(), devices=[0], launcher=_launcher(h))
    assert m.status == "ok" and m.tok_s == 14.2 and m.peak_vram == {0: 100}
    assert h.killed and h.vram_waited

def test_measure_oom():
    h = FakeHandle(listened=False, stderr="cudaMalloc failed: out of memory")
    assert measure(_cand(), devices=[0], launcher=_launcher(h)).status == "oom"

def test_measure_hardware_error():
    h = FakeHandle(listened=True, tokens=1, stderr="an illegal memory access was encountered")
    assert measure(_cand(), devices=[0], launcher=_launcher(h)).status == "hardware_error"

def test_measure_garbage():
    h = FakeHandle(listened=True, tokens=10, out="a a a a a a a a a a")
    assert measure(_cand(), devices=[0], launcher=_launcher(h)).status == "garbage"

def test_measure_always_tears_down():
    h = FakeHandle(listened=False, stderr="whatever")
    measure(_cand(), devices=[0], launcher=_launcher(h))
    assert h.killed


def test_port_open_detects_listening_socket_version_agnostic():
    # readiness is the open port, not a log string (which changed across llama.cpp versions)
    import socket
    from soveryn.platform.tuner.measure import _port_open
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert _port_open("127.0.0.1", port) is True
    finally:
        s.close()
    assert _port_open("127.0.0.1", port) is False
