"""Report which GPU a job received and whether PyTorch can use it: a tiny GPU demo job.

    python gpu_check.py
"""

import socket

import torch

print(f"host={socket.gethostname()}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    device = torch.cuda.get_device_name(0)
    x = torch.rand(4096, 4096, device="cuda")
    print(f"GPU: {device}; 4096x4096 matrix product checksum = {(x @ x).sum().item():.1f}")
