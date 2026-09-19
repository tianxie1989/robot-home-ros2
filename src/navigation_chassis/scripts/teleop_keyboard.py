#!/usr/bin/env python3
"""键盘遥控 - 建图时手动控制机器人移动"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import sys
import termios
import tty


class TeleopKeyboardNode(Node):
    """键盘遥控节点"""

    def __init__(self):
        super().__init__('teleop_keyboard')
        self.publisher = self.create_publisher(Twist, '/cmd_vel', 10)
        self.linear_speed = 0.2
        self.angular_speed = 0.5
        self.get_logger().info('键盘遥控已启动 (w/s: 前进/后退, a/d: 左转/右转, q: 退出)')

    def run(self):
        settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setraw(sys.stdin.fileno())
            while rclpy.ok():
                key = sys.stdin.read(1)
                twist = Twist()
                if key == 'w':
                    twist.linear.x = self.linear_speed
                elif key == 's':
                    twist.linear.x = -self.linear_speed
                elif key == 'a':
                    twist.angular.z = self.angular_speed
                elif key == 'd':
                    twist.angular.z = -self.angular_speed
                elif key == 'q':
                    break
                else:
                    twist = Twist()  # 停止
                self.publisher.publish(twist)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
            # 发送停止命令
            self.publisher.publish(Twist())


def main(args=None):
    rclpy.init(args=args)
    node = TeleopKeyboardNode()
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
