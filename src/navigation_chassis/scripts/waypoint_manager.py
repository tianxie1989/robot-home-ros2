#!/usr/bin/env python3
"""航点管理工具 - 保存和加载导航航点"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String
import json
import os


class WaypointManagerNode(Node):
    """航点管理节点"""

    def __init__(self):
        super().__init__('waypoint_manager')
        self.waypoints = {}
        self.waypoint_file = os.path.expanduser('~/.robot_home/waypoints.json')

        self.declare_parameter('waypoint_file', self.waypoint_file)
        self.waypoint_file = self.get_parameter('waypoint_file').value

        # 加载已有航点
        self._load_waypoints()

        # 服务接口（简单使用topic）
        self.cmd_sub = self.create_subscription(
            String, '/waypoint/command', self.command_callback, 10
        )
        self.status_pub = self.create_publisher(String, '/waypoint/status', 10)

        self.get_logger().info(f'航点管理器启动, 已加载 {len(self.waypoints)} 个航点')

    def command_callback(self, msg):
        """处理航点命令"""
        try:
            cmd = json.loads(msg.data)
            action = cmd.get('action', '')

            if action == 'save':
                name = cmd['name']
                pose = cmd['pose']
                self.waypoints[name] = pose
                self._save_waypoints()
                self._publish_status(f'航点已保存: {name}')

            elif action == 'delete':
                name = cmd['name']
                if name in self.waypoints:
                    del self.waypoints[name]
                    self._save_waypoints()
                    self._publish_status(f'航点已删除: {name}')

            elif action == 'list':
                self._publish_status(json.dumps(list(self.waypoints.keys())))

            elif action == 'get':
                name = cmd['name']
                if name in self.waypoints:
                    self._publish_status(json.dumps(self.waypoints[name]))

        except Exception as e:
            self._publish_status(f'错误: {e}')

    def _save_waypoints(self):
        os.makedirs(os.path.dirname(self.waypoint_file), exist_ok=True)
        with open(self.waypoint_file, 'w') as f:
            json.dump(self.waypoints, f, indent=2)

    def _load_waypoints(self):
        if os.path.exists(self.waypoint_file):
            with open(self.waypoint_file, 'r') as f:
                self.waypoints = json.load(f)

    def _publish_status(self, msg):
        status = String()
        status.data = msg
        self.status_pub.publish(status)


def main(args=None):
    rclpy.init(args=args)
    node = WaypointManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

