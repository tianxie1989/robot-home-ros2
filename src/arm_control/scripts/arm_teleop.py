#!/usr/bin/env python3
"""
机械臂遥控脚本
arm_control/scripts/arm_teleop.py

通过键盘输入控制机械臂各关节运动及夹爪开合:
- 按键 1-6: 选择要控制的关节
- 按键 q/a: 增加/减少选中关节角度
- 按键 o/p: 打开/闭合夹爪
- 按键 h: 回到初始位姿
- 按键 x: 退出
"""

import sys
import select
import termios
import tty
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from builtin_interfaces.msg import Duration
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from sensor_msgs.msg import JointState
from control_msgs.action import GripperCommand


HELP_TEXT = """
========== 机械臂键盘遥控 ==========
关节选择:
  1 - joint_1  (基座旋转)
  2 - joint_2  (肩关节)
  3 - joint_3  (肘关节)
  4 - joint_4  (腕旋转)
  5 - joint_5  (腕俯仰)
  6 - joint_6  (末端旋转)

运动控制:
  q   - 选中关节角度 +0.05 rad
  a   - 选中关节角度 -0.05 rad
  w   - 选中关节角度 +0.20 rad (大步)
  s   - 选中关节角度 -0.20 rad (大步)

夹爪控制:
  o   - 打开夹爪
  p   - 闭合夹爪

其他:
  h   - 回到初始位姿
  r   - 打印当前关节角度
  x   - 退出
====================================
"""


class ArmTeleop(Node):
    """机械臂键盘遥控节点"""

    ARM_JOINTS = [
        'joint_1', 'joint_2', 'joint_3',
        'joint_4', 'joint_5', 'joint_6'
    ]

    JOINT_LIMITS = [
        (-3.14, 3.14),    # joint_1
        (-2.0, 2.0),      # joint_2
        (-2.5, 2.5),      # joint_3
        (-3.14, 3.14),    # joint_4
        (-2.0, 2.0),      # joint_5
        (-3.14, 3.14),    # joint_6
    ]

    HOME_POSITION = [0.0, -0.5, 0.8, 0.0, 1.2, 0.0]

    def __init__(self):
        super().__init__('arm_teleop')

        # 当前关节角度
        self.current_joints = list(self.HOME_POSITION)
        self.selected_joint = 0

        # 轨迹发布
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

        # 订阅关节状态
        self.joint_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            10
        )

        self.get_logger().info('机械臂遥控节点已启动')
        print(HELP_TEXT)

    def joint_state_callback(self, msg: JointState):
        """更新当前关节状态"""
        for i, name in enumerate(self.ARM_JOINTS):
            if name in msg.name:
                idx = msg.name.index(name)
                self.current_joints[i] = msg.position[idx]

    def publish_joint_cmd(self):
        """发布当前关节角度指令"""
        traj = JointTrajectory()
        traj.joint_names = self.ARM_JOINTS

        point = JointTrajectoryPoint()
        point.positions = list(self.current_joints)
        point.velocities = [0.0] * 6
        point.accelerations = [0.0] * 6
        point.time_from_start = Duration(sec=0, nanosec=500000000)  # 0.5s
        traj.points.append(point)

        self.arm_pub.publish(traj)

    def move_joint(self, delta: float):
        """移动选中的关节"""
        new_val = self.current_joints[self.selected_joint] + delta
        low, high = self.JOINT_LIMITS[self.selected_joint]
        new_val = max(low, min(high, new_val))
        self.current_joints[self.selected_joint] = new_val

        self.get_logger().info(
            f'{self.ARM_JOINTS[self.selected_joint]}: {new_val:.3f} rad'
        )
        self.publish_joint_cmd()

    def control_gripper(self, position: float):
        """控制夹爪"""
        goal = GripperCommand.Goal()
        goal.command.position = position
        goal.command.max_effort = 50.0

        if not self.gripper_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn('夹爪服务器不可用，跳过夹爪指令')
            return

        self.gripper_client.send_goal_async(goal)
        action = '打开' if position > 0.02 else '闭合'
        self.get_logger().info(f'夹爪{action}指令已发送')

    def go_home(self):
        """回到初始位姿"""
        self.current_joints = list(self.HOME_POSITION)
        self.publish_joint_cmd()
        self.get_logger().info('回到初始位姿')

    def print_status(self):
        """打印当前关节状态"""
        print('\n--- 当前关节角度 ---')
        for i, name in enumerate(self.ARM_JOINTS):
            marker = ' <-- 选中' if i == self.selected_joint else ''
            print(f'  {name}: {self.current_joints[i]:+.3f} rad{marker}')
        print('--------------------\n')

    def process_key(self, key: str):
        """处理键盘输入"""
        if key in '123456':
            self.selected_joint = int(key) - 1
            self.get_logger().info(f'选中关节: {self.ARM_JOINTS[self.selected_joint]}')

        elif key == 'q':
            self.move_joint(0.05)
        elif key == 'a':
            self.move_joint(-0.05)
        elif key == 'w':
            self.move_joint(0.20)
        elif key == 's':
            self.move_joint(-0.20)

        elif key == 'o':
            self.control_gripper(0.04)
        elif key == 'p':
            self.control_gripper(0.0)

        elif key == 'h':
            self.go_home()
        elif key == 'r':
            self.print_status()

        elif key == 'x':
            return True  # 退出信号

        return False


def get_key(settings):
    """非阻塞获取单个按键"""
    tty.setraw(sys.stdin.fileno())
    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
    if rlist:
        key = sys.stdin.read(1)
    else:
        key = ''
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
    return key


def main(args=None):
    rclpy.init(args=args)
    node = ArmTeleop()

    settings = termios.tcgetattr(sys.stdin)

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            key = get_key(settings)
            if key:
                if node.process_key(key):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        node.get_logger().info('遥控已退出')
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
