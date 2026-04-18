import torch
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained("D:/research/Live-Vision-Narrator/models/hub/Qwen3.5-9B", device_map="auto")
print(model.model.layers[0])
