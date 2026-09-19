"""
机械臂控制器启动文件
arm_control/launch/arm_controller.launch.py

启动 ros2_control 控制器管理器和关节轨迹控制器
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, Command
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from launch.event_handlers import OnProcessExit


def generate_launch_description():
    # 包路径
    arm_control_pkg = FindPackageShare('arm_control')
    description_pkg = FindPackageShare('robot_home_description')

    # 配置文件
    controller_config = PathJoinSubstitution([
        arm_control_pkg, 'config', 'joint_trajectory_controller.yaml'
    ])

    robot_urdf_xacro = PathJoinSubstitution([
        description_pkg, 'urdf', 'robot_home.urdf.xacro'
    ])

    robot_description = Command(['xacro ', robot_urdf_xacro])

    # robot_state_publisher
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'publish_frequency': 50.0,
        }],
    )

    # 控制器管理器
    controller_manager_node = Node(
        package='controller_manager',
        executable='ros2_control_node',
        parameters=[
            {'robot_description': robot_description},
            controller_config,
        ],
        output='screen',
    )

    # 关节状态广播器
    joint_state_broadcaster_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=['joint_state_broadcaster', '--controller-manager', '/controller_manager'],
        output='screen',
    )

    # 机械臂轨迹控制器
    arm_controller_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=['arm_controller', '--controller-manager', '/controller_manager'],
        output='screen',
    )

    # 夹爪控制器
    gripper_controller_spawner = Node(
        package='controller_manager',
        executable='spawner',
        arguments=['gripper_controller', '--controller-manager', '/controller_manager'],
        output='screen',
    )

    # 确保控制器按顺序启动
    delay_arm_controller = RegisterEventHandler(
        event_handler=OnProcessExit(
            target_action=joint_state_broadcaster_spawner,
            on_exit=[arm_controller_spawner],
        )
    )

    delay_gripper_controller = RegisterEventHandler(
        event_handler=OnProcessExit(
            target_action=arm_controller_spawner,
            on_exit=[gripper_controller_spawner],
        )
    )

    return LaunchDescription([
        robot_state_publisher_node,
        controller_manager_node,
        joint_state_broadcaster_spawner,
        delay_arm_controller,
        delay_gripper_controller,
    ])
