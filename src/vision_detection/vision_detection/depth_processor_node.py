"""深度图像处理节点 - 将RGB+深度图转换为3D物体位姿"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, PointCloud2
from std_msgs.msg import Header, String
import numpy as np
import json


class DepthProcessorNode(Node):
    """深度处理节点，结合RGB检测和深度图获取3D位姿"""

    def __init__(self):
        super().__init__('depth_processor')

        # 相机内参（默认值，后续从标定文件加载）
        self.declare_parameter('fx', 600.0)
        self.declare_parameter('fy', 600.0)
        self.declare_parameter('cx', 320.0)
        self.declare_parameter('cy', 240.0)

        self.fx = self.get_parameter('fx').value
        self.fy = self.get_parameter('fy').value
        self.cx = self.get_parameter('cx').value
        self.cy = self.get_parameter('cy').value

        # 订阅检测结果和深度图
        self.detection_sub = self.create_subscription(
            String, '/detected_objects', self.detection_callback, 10
        )
        self.depth_sub = self.create_subscription(
            Image, '/camera/depth/image_raw', self.depth_callback, 10
        )

        # 发布3D位姿
        self.pose_pub = self.create_publisher(String, '/object_poses_3d', 10)

        self.latest_depth = None
        self.get_logger().info('深度处理节点启动完成')

    def depth_callback(self, msg):
        """缓存最新深度图"""
        depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
        self.latest_depth = depth.astype(np.float32) / 1000.0  # 毫米 -> 米

    def detection_callback(self, msg):
        """处理检测结果，添加3D位置信息"""
        if self.latest_depth is None:
            return

        data = json.loads(msg.data)
        objects_3d = []

        for obj in data.get('objects', []):
            # 计算边界框中心点
            cx = obj['bbox_x'] + obj['bbox_width'] // 2
            cy = obj['bbox_y'] + obj['bbox_height'] // 2

            # 从深度图获取深度值
            if cy < self.latest_depth.shape[0] and cx < self.latest_depth.shape[1]:
                depth_val = self.latest_depth[cy, cx]
                if depth_val > 0.1 and depth_val < 5.0:  # 有效深度范围
                    # 反投影到3D相机坐标
                    x = (cx - self.cx) * depth_val / self.fx
                    y = (cy - self.cy) * depth_val / self.fy
                    z = depth_val

                    objects_3d.append({
                        'class_name': obj['class_name'],
                        'confidence': obj['confidence'],
                        'position_3d': {'x': round(x, 3), 'y': round(y, 3), 'z': round(z, 3)},
                    })

        if objects_3d:
            result = String()
            result.data = json.dumps({
                'header': data.get('header', {}),
                'objects_3d': objects_3d,
            })
            self.pose_pub.publish(result)

    def pixel_to_3d(self, u, v, depth):
        """像素坐标转3D相机坐标"""
        x = (u - self.cx) * depth / self.fx
        y = (v - self.cy) * depth / self.fy
        z = depth
        return x, y, z


def main(args=None):
    rclpy.init(args=args)
    node = DepthProcessorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
