import torch
import sys

print("Python版本:", sys.version)
print("PyTorch版本:", torch.__version__)
print("CUDA是否可用:", torch.cuda.is_available())
print("CUDA设备数量:", torch.cuda.device_count())
if torch.cuda.is_available():
    print("CUDA设备名称:", torch.cuda.get_device_name(0))
    print("当前设备:", torch.cuda.current_device())
    print("CUDA版本:", torch.version.cuda)
else:
    print("CUDA不可用，程序将使用CPU运行") 