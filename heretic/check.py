import torch
import torchvision

print("torch:", torch.__version__)

print("cuda available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("device name:", torch.cuda.get_device_name(0))

print(f"PyTorch CUDA version: {torch.version.cuda}")

print(f"torchvision version: {torchvision.__version__}")
