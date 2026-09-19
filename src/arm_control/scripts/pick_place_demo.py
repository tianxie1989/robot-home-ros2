#!/usr/bin/env python3
"""
抓取-放置演示脚本
arm_control/scripts/pick_place_demo.py

使用 MoveIt2 Python API 执行简单的抓取-放置任务:
1. 移动到预抓取位姿
2. 打开夹爪
3. 移动到抓取位姿
4. 闭合夹爪
5. 抬起
6. 移动到放置位姿
7. 打开夹爪释放
"""

import sys
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from builtin_interfaces.msg import Duration
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from control_msgs.action import GripperCommand
from std_msgs.msg import Header


class PickPlaceDemo(Node):
    """抓取-放置演示节点"""

    ARM_JOINTS = [
        'joint_1', 'joint_2', 'joint_3',
        'joint_4', 'joint_5', 'joint_6'
    ]

    def __init__(self):
        super().__init__('pick_place_demo')

        # 机械臂轨迹发布
        self.arm_pub = self.create_publisher(
            JointTrajectory,
            '/arm_controller/joint_trajectory',
            10
        )

        # 夹爪动作客户端
        self.gripper_client = ActionClient(
            self,
            GripperCommand,
            '/gripper_controller/gripper_cmd'
        )

        self.get_logger().info('抓取-放置演示节点已初始化')

    def create_trajectory(self, joint_positions: list, duration_sec: float) -> JointTrajectory:
        """创建关节轨迹消息"""
        traj = JointTrajectory()
        traj.joint_names = self.ARM_JOINTS

        point = JointTrajectoryPoint()
        point.positions = joint_positions
        point.velocities = [0.0] * len(joint_positions)
        point.accelerations = [0.0] * len(joint_positions)
        point.time_from_start = Duration(
            sec=int(duration_sec),
            nanosec=int((duration_sec - int(duration_sec)) * 1e9)
        )
        traj.points.append(point)
        return traj

    def move_arm(self, joint_positions: list, duration_sec: float = 3.0):
        """发送关节目标位置"""
        self.get_logger().info(
            f'移动机械臂到: {[round(p, 3) for p in joint_positions]}'
        )
        traj = self.create_trajectory(joint_positions, duration_sec)
        self.arm_pub.publish(traj)
        # 等待运动完成
        self._sleep(duration_sec + 0.5)

    def control_gripper(self, position: float, max_effort: float = 50.0):
        """控制夹爪开合。position: 0.0=完全闭合, 0.04=完全打开"""
        self.get_logger().info(f'夹爪动作: position={position}, effort={max_effort}')

        goal = GripperCommand.Goal()
        goal.command.position = position
        goal.command.max_effort = max_effort

        if not self.gripper_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('夹爪动作服务器不可用')
            return

        future = self.gripper_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, future)
        goal_handle = future.result()

        if not goal_handle.accepted:
            self.get_logger().error('夹爪动作被拒绝')
            return

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)
        self.get_logger().info('夹爪动作完成')

    def _sleep(self, seconds: float):
        """非阻塞等待"""
        import time
        end_time = time.time() + seconds
        while rclpy.ok() and time.time() < end_time:
            rclpy.spin_once(self, timeout_sec=0.1)

    def run_demo(self):
        """执行完整的抓取-放置流程"""
        self.get_logger().info('========== 抓取-放置演示开始 ==========')

        # 定义关键位姿 (关节角度，弧度)
        home_position = [0.0, -0.5, 0.8, 0.0, 1.2, 0.0]
        pre_pick_position = [0.3, -0.8, 1.0, 0.0, 1.5, 0.3]
        pick_position = [0.3, -1.0, 1.2, 0.0, 1.6, 0.3]
        lift_position = [0.3, -0.6, 0.9, 0.0, 1.3, 0.3]
        pre_place_position = [-0.5, -0.7, 0.9, 0.0, 1.4, -0.5]
        place_position = [-0.5, -0.9, 1.1, 0.0, 1.5, -0.5]

        # 步骤1: 回到初始位姿
        self.get_logger().info('步骤1: 移动到初始位姿')
        self.move_arm(home_position, duration_sec=2.0)

        # 步骤2: 移动到预抓取位姿
        self.get_logger().info('步骤2: 移动到预抓取位姿')
        self.move_arm(pre_pick_position, duration_sec=3.0)

        # 步骤3: 打开夹爪
        self.get_logger().info('步骤3: 打开夹爪')
        self.control_gripper(position=0.04)

        # 步骤4: 下降到抓取位姿
        self.get_logger().info('步骤4: 下降到抓取位姿')
        self.move_arm(pick_position, duration_sec=2.0)

        # 步骤5: 闭合夹爪抓取
        self.get_logger().info('步骤5: 闭合夹爪抓取')
        self.control_gripper(position=0.0, max_effort=80.0)

        # 步骤6: 抬起
        self.get_logger().info('步骤6: 抬起物体')
        self.move_arm(lift_position, duration_sec=2.0)

        # 步骤7: 移动到预放置位姿
        self.get_logger().info('步骤7: 移动到预放置位姿')
        self.move_arm(pre_place_position, duration_sec=3.0)

        # 步骤8: 下降到放置位姿
        self.get_logger().info('步骤8: 下降到放置位姿')
        self.move_arm(place_position, duration_sec=2.0)

        # 步骤9: 打开夹爪释放
        self.get_logger().info('步骤9: 打开夹爪释放物体')
        self.control_gripper(position=0.04)

        # 步骤10: 回到初始位姿
        self.get_logger().info('步骤10: 回到初始位姿')
        self.move_arm(home_position, duration_sec=3.0)

        self.get_logger().info('========== 抓取-放置演示完成 ==========')


def main(args=None):
    rclpy.init(args=args)
    node = PickPlaceDemo()

    try:
        node.run_demo()
    except KeyboardInterrupt:
        node.get_logger().info('演示被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
