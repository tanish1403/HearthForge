from hearthforge import hardware

GTX1650 = {"ram_gb": 16.0, "ram_available_gb": 10.0, "disk_free_gb": 200, "gpus": [{"vendor": "nvidia", "name": "GTX 1650", "vram_gb": 4.0, "unified": False}]}
NO_GPU_8GB = {"ram_gb": 8.0, "ram_available_gb": 4.0, "disk_free_gb": 5, "gpus": []}
BIG = {"ram_gb": 64.0, "ram_available_gb": 48.0, "disk_free_gb": 900, "gpus": [{"vendor": "nvidia", "name": "4090", "vram_gb": 24.0, "unified": False}]}


def verdicts(hw):
    return {r["params_b"]: r["verdict"] for r in hardware.recommend(hw)["options"]}


def test_4gb_vram_machine():
    v = verdicts(GTX1650)
    assert v[3] == "gpu" and v[7] == "hybrid" and v[32] == "no"


def test_cpu_only_low_ram_machine():
    v = verdicts(NO_GPU_8GB)
    assert v[1.5] == "cpu" and v[7] in ("no",) and v[32] == "no"
    rec = hardware.recommend(NO_GPU_8GB)
    assert rec["suggested"]["params_b"] <= 3 and rec["disk_warning"]


def test_large_gpu_fits_more():
    v = verdicts(BIG)
    assert v[14] == "gpu"


def test_estimates_state_uncertainty():
    e = hardware.estimate_gb(7)
    assert e["total_gb"] > e["weights_gb"] and "+/-" in e["uncertainty"]
    assert hardware.estimate_gb(7, "Q8_0")["weights_gb"] > hardware.estimate_gb(7, "Q4_K_M")["weights_gb"]
    assert hardware.estimate_gb(7, ctx=32768)["kv_cache_gb"] > hardware.estimate_gb(7, ctx=4096)["kv_cache_gb"]


def test_detect_runs_here():
    hw = hardware.detect()
    assert hw["ram_gb"] > 0 and isinstance(hw["gpus"], list)
