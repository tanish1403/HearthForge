# Hardware recommendations

The **Hardware fit** page detects RAM, free disk, and NVIDIA GPUs (via `nvidia-smi`) and estimates memory for common model sizes at Q4_K_M.

Formula (rough): `weights ≈ params_B × bits/8`, `KV cache ≈ 0.05 × params_B × ctx/4096 GB`, `+0.5 GB` overhead. Accuracy is about ±40%; real use depends on the
model architecture, backend, flash-attention and other apps. Verdicts: *Fits GPU*, *GPU + CPU* (partial offload), *CPU only*, *Too large*.

Worked example from the unit tests, 16 GB RAM + 4 GB VRAM (GTX 1650 class): ≈3B fits the GPU; 7B needs GPU+CPU offload; 14B+ is too large for comfort.
No-GPU 8 GB machines: ≤3B on CPU only, slowly.

Guidance (not guarantees): coding agents need models that follow strict JSON; try 7B coder-tuned models first, drop to smaller only for plan/explain tasks,
and consider a free-tier remote model for heavy work *if* you accept the privacy trade-off. Nothing is downloaded automatically.
Apple Silicon unified memory and AMD/Intel GPUs are not measured: they are treated by heuristic or as CPU.
