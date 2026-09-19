"""目标检测节点 - YOLO推理，检测家居物品"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Header
import numpy as np
import time

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from cv_bridge import CvBridge
except ImportError:
    CvBridge = None


# 家居物品类别映射
HOME_CLASSES = {
    'toy_block': 0,
    'plush_toy': 1,
    'toy_car': 2,
    'ball': 3,
    'book': 4,
    'clothes': 5,
    'shoes': 6,
    'storage_box': 7,
    'cup': 8,
    'remote_control': 9,
}

# COCO到家居类别的近似映射（使用预训练COCO模型时的映射）
COCO_TO_HOME = {
    'sports ball': 'ball',
    'book': 'book',
    'cup': 'cup',
    'tv remote': 'remote_control',
}


class ObjectDetectorNode(Node):
    """目标检测节点，订阅图像并发布检测结果"""

    def __init__(self):
        super().__init__('object_detector')

        # 参数
        self.declare_parameter('model_path', 'yolov8n')
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('nms_threshold', 0.45)
        self.declare_parameter('input_size', 640)
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('detection_rate', 5.0)
        self.declare_parameter('publish_debug_image', True)

        self.confidence_threshold = self.get_parameter('confidence_threshold').value
        self.input_size = self.get_parameter('input_size').value
        self.device = self.get_parameter('device').value
        self.publish_debug = self.get_parameter('publish_debug_image').value

        # 初始化模型
        model_path = self.get_parameter('model_path').value
        self._init_model(model_path)

        # cv_bridge
        if CvBridge is not None:
            self.bridge = CvBridge()
        else:
            self.bridge = None
            self.get_logger().warn('cv_bridge不可用，使用手动转换')

        # 订阅摄像头图像
        self.image_sub = self.create_subscription(
            Image, '/camera/color/image_raw', self.image_callback, 10
        )

        # 发布检测结果（使用标准JSON字符串，后续替换为自定义消息）
        from std_msgs.msg import String
        self.result_pub = self.create_publisher(String, '/detected_objects', 10)

        if self.publish_debug:
            self.debug_image_pub = self.create_publisher(Image, '/debug/detection_image', 10)

        # 频率控制
        self.last_detect_time = 0
        self.detect_interval = 1.0 / self.get_parameter('detection_rate').value

        self.get_logger().info(f'目标检测节点启动完成 (device={self.device})')

    def _init_model(self, model_path):
        """初始化YOLO模型"""
        if YOLO is None:
            self.get_logger().error('ultralytics未安装，检测功能不可用')
            self.model = None
            return

        try:
            self.model = YOLO(model_path)
            self.get_logger().info(f'模型加载成功: {model_path}')
        except Exception as e:
            self.get_logger().error(f'模型加载失败: {e}')
            self.model = None

    def image_callback(self, msg):
        """处理接收到的图像帧"""
        now = time.time()
        if now - self.last_detect_time < self.detect_interval:
            return
        self.last_detect_time = now

        if self.model is None:
            return

        # 转换为numpy数组
        start_time = time.time()
        frame = self._image_msg_to_numpy(msg)
        if frame is None:
            return

        # YOLO推理
        results = self.model(
            frame,
            conf=self.confidence_threshold,
            imgsz=self.input_size,
            device=self.device,
            verbose=False,
        )

        # 解析结果
        detections = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = result.names.get(cls_id, 'unknown')
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # 映射到家居类别
                home_class = COCO_TO_HOME.get(cls_name, cls_name)

                detections.append({
                    'class_name': home_class,
                    'class_id': HOME_CLASSES.get(home_class, -1),
                    'confidence': round(conf, 3),
                    'bbox_x': int(x1),
                    'bbox_y': int(y1),
                    'bbox_width': int(x2 - x1),
                    'bbox_height': int(y2 - y1),
                })

        inference_time = (time.time() - start_time) * 1000

        # 发布结果
        from std_msgs.msg import String
        import json
        result_msg = String()
        result_msg.data = json.dumps({
            'header': {
                'stamp': {'sec': msg.header.stamp.sec, 'nanosec': msg.header.stamp.nanosec},
                'frame_id': msg.header.frame_id,
            },
            'objects': detections,
            'total_count': len(detections),
            'inference_time_ms': round(inference_time, 1),
        })
        self.result_pub.publish(result_msg)

        if len(detections) > 0:
            self.get_logger().info(
                f'检测到 {len(detections)} 个物品, 推理耗时 {inference_time:.1f}ms'
            )

        # 发布调试图像
        if self.publish_debug and len(detections) > 0:
            debug_frame = results[0].plot()
            self._publish_debug_image(debug_frame, msg.header)

    def _image_msg_to_numpy(self, msg):
        """将ROS2 Image消息转换为numpy数组"""
        if self.bridge is not None:
            try:
                return self.bridge.imgmsg_to_cv2(msg, 'rgb8')
            except Exception as e:
                self.get_logger().warn(f'cv_bridge转换失败: {e}')
                return None
        else:
            # 手动转换
            dtype = np.uint8
            if msg.encoding == 'rgb8':
                frame = np.frombuffer(msg.data, dtype=dtype).reshape(msg.height, msg.width, 3)
                return frame
            elif msg.encoding == 'bgr8':
                frame = np.frombuffer(msg.data, dtype=dtype).reshape(msg.height, msg.width, 3)
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None

    def _publish_debug_image(self, frame, header):
        """发布带标注的调试图像"""
        if self.bridge is not None:
            try:
                msg = self.bridge.cv2_to_imgmsg(frame, 'rgb8')
                msg.header = header
                self.debug_image_pub.publish(msg)
                return
            except Exception:
                pass

        # 手动转换
        import cv2
        if frame.shape[2] == 3:
            msg = Image()
            msg.header = header
            msg.height = frame.shape[0]
            msg.width = frame.shape[1]
            msg.encoding = 'rgb8'
            msg.is_bigendian = False
            msg.step = frame.shape[1] * 3
            msg.data = frame.tobytes()
            self.debug_image_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ObjectDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
