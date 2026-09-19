"""摄像头驱动节点 - 支持USB摄像头和macOS内置摄像头"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Header
import cv2
import numpy as np
import time


class CameraDriverNode(Node):
    """摄像头驱动节点，发布RGB图像流"""

    def __init__(self):
        super().__init__('camera_driver')

        # 参数声明
        self.declare_parameter('device_index', 0)
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30)
        self.declare_parameter('use_cv_capture', True)  # macOS开发模式
        self.declare_parameter('show_image', False)  # 是否显示图像窗口

        device_index = self.get_parameter('device_index').value
        width = self.get_parameter('width').value
        height = self.get_parameter('height').value
        fps = self.get_parameter('fps').value
        self.show_image = self.get_parameter('show_image').value

        # 初始化OpenCV摄像头
        self.get_logger().info(f'初始化摄像头: device_index={device_index}')
        self.cap = cv2.VideoCapture(device_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)

        if not self.cap.isOpened():
            self.get_logger().error('无法打开摄像头!')
            return

        self.get_logger().info(
            f'摄像头已打开: {int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x'
            f'{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}'
        )

        # 发布者
        self.image_pub = self.create_publisher(Image, '/camera/color/image_raw', 10)
        self.info_pub = self.create_publisher(CameraInfo, '/camera/color/camera_info', 10)

        # 定时器（按FPS采集）
        timer_period = 1.0 / fps
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.frame_id = 'camera_link'
        if self.show_image:
            cv2.namedWindow('Camera View', cv2.WINDOW_NORMAL)
            self.get_logger().info('图像显示窗口已开启 (按 q 退出)')
        self.get_logger().info('摄像头驱动节点启动完成')

    def timer_callback(self):
        """采集并发布图像帧"""
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn('读取摄像头帧失败')
            return

        # BGR -> RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # 构建ROS2 Image消息
        msg = Image()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.height = frame_rgb.shape[0]
        msg.width = frame_rgb.shape[1]
        msg.encoding = 'rgb8'
        msg.is_bigendian = False
        msg.step = frame_rgb.shape[1] * 3
        msg.data = frame_rgb.tobytes()

        self.image_pub.publish(msg)

        # 显示图像
        if self.show_image:
            display = frame.copy()
            cv2.putText(display, f'FPS: {fps}', (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow('Camera View', display)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.get_logger().info('用户按下 q，退出')
                rclpy.shutdown()
                return

        # 发布简单CameraInfo
        info = CameraInfo()
        info.header = msg.header
        info.height = frame_rgb.shape[0]
        info.width = frame_rgb.shape[1]
        self.info_pub.publish(info)

    def destroy_node(self):
        self.get_logger().info('关闭摄像头')
        if self.show_image:
            cv2.destroyAllWindows()
        if self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraDriverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
