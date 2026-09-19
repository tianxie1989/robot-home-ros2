"""YOLO检测器封装"""
import time


class YOLODetector:
    """YOLO检测器统一接口"""

    def __init__(self, model_path='yolov8n', device='cpu'):
        try:
            from ultralytics import YOLO
            self.model = YOLO(model_path)
            self.device = device
            self.available = True
        except ImportError:
            self.model = None
            self.available = False

    def detect(self, frame, conf=0.5, imgsz=640):
        """执行检测"""
        if not self.available:
            return []
        results = self.model(frame, conf=conf, imgsz=imgsz, device=self.device, verbose=False)
        return results

    def export_onnx(self, output_path='model.onnx', opset=12):
        """导出ONNX模型"""
        if self.available:
            self.model.export(format='onnx', opset=opset)
