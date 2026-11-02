"""Hardware detection and local-model fit estimates. Estimates are rough and say so."""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import psutil

QUANTS = {"Q4_K_M": 4.8, "Q5_K_M": 5.7, "Q8_0": 8.5, "F16": 16.0}


def detect_gpus() -> list[dict]:
    gpus: list[dict] = []
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run([exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8).stdout
            for ln in out.strip().splitlines():
                name, total, free = [x.strip() for x in ln.split(",")]
                gpus.append({"vendor": "nvidia", "name": name, "vram_gb": round(float(total) / 1024, 2),
                             "vram_free_gb": round(float(free) / 1024, 2), "unified": False, "verified": True})
        except Exception:
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        gpus.append({"vendor": "apple", "name": "Apple Silicon (unified memory)", "vram_gb": 0.0, "unified": True, "verified": False})
    return gpus


def detect(path: str | Path | None = None) -> dict:
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(str(path or Path.home()))
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or platform.machine(),
        "cpu_threads": psutil.cpu_count(logical=True),
        "ram_gb": round(vm.total / 2**30, 1),
        "ram_available_gb": round(vm.available / 2**30, 1),
        "disk_free_gb": round(disk.free / 2**30, 1),
        "gpus": detect_gpus(),
    }


def estimate_gb(params_b: float, quant: str = "Q4_K_M", ctx: int = 8192) -> dict:
    weights = params_b * QUANTS[quant] / 8 * 1.03
    kv = 0.05 * params_b * (ctx / 4096)
    overhead = 0.5
    return {"weights_gb": round(weights, 2), "kv_cache_gb": round(kv, 2), "overhead_gb": overhead,
            "total_gb": round(weights + kv + overhead, 2), "uncertainty": "roughly +/-40%; depends on architecture and backend"}


def fit(hw: dict, params_b: float, quant: str = "Q4_K_M", ctx: int = 8192) -> dict:
    est = estimate_gb(params_b, quant, ctx)
    need = est["total_gb"]
    gpu = max(hw["gpus"], key=lambda g: g["vram_gb"], default=None)
    vram = gpu["vram_gb"] * 0.9 if gpu and not gpu.get("unified") else 0.0
    ram = hw["ram_available_gb"] * 0.7
    if gpu and gpu.get("unified"):
        verdict, note = ("gpu", "unified memory (not verified)") if need <= hw["ram_gb"] * 0.65 else ("no", "exceeds unified memory budget")
    elif vram and need <= vram:
        verdict, note = "gpu", "fits in VRAM"
    elif vram >= 1.5 and need <= vram + ram:
        verdict, note = "hybrid", "partial GPU offload; slower than full GPU"
    elif need <= ram:
        verdict, note = "cpu", "CPU only; expect slow generation"
    else:
        verdict, note = "no", "does not fit comfortably in memory"
    return {"params_b": params_b, "quant": quant, "ctx": ctx, **est, "verdict": verdict, "note": note,
            "disk_gb": round(est["weights_gb"], 1)}


SIZES = [1.5, 3, 7, 8, 14, 32]


def recommend(hw: dict, ctx: int = 8192) -> dict:
    rows = [fit(hw, s, "Q4_K_M", ctx) for s in SIZES]
    usable = [r for r in rows if r["verdict"] == "gpu"] or [r for r in rows if r["verdict"] == "hybrid" and r["params_b"] <= 8] \
        or [r for r in rows if r["verdict"] == "cpu" and r["params_b"] <= 3]
    pick = max(usable, key=lambda r: r["params_b"]) if usable else None
    return {
        "hardware": hw, "context": ctx, "options": rows, "suggested": pick,
        "notes": [
            "Quantization assumed Q4_K_M. Estimates ignore concurrent apps and backend differences.",
            "Example families worth trying for code: Qwen2.5-Coder and similar open models; check the Ollama library for exact tags.",
            "Nothing is downloaded automatically. Large downloads need your explicit action.",
        ],
        "disk_warning": hw["disk_free_gb"] < 10,
    }
