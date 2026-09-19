"""
MoveIt2 启动文件
arm_control/launch/moveit.launch.py

启动 MoveIt2 规划框架，包括 move_group 节点和 RViz 可视化
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, Command
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 包路径
    arm_control_pkg = FindPackageShare('arm_control')
    description_pkg = FindPackageShare('robot_home_description')

    # 配置文件路径
    moveit_config_file = PathJoinSubstitution([
        arm_control_pkg, 'config', 'moveit_config.yaml'
    ])

    robot_urdf_xacro = PathJoinSubstitution([
        description_pkg, 'urdf', 'robot_home.urdf.xacro'
    ])

    # 通过 xacro 处理 URDF
    robot_description = Command(['xacro ', robot_urdf_xacro])

    # MoveIt2 配置参数
    robot_description_semantic = Command([
        'cat ',
        PathJoinSubstitution([arm_control_pkg, 'moveit_config', 'robot_home.srdf'])
    ])

    # move_group 节点参数
    moveit_config = {
        'robot_description': robot_description,
        'robot_description_semantic': robot_description_semantic,
        'planning_pipelines': ['ompl'],
        'ompl': {
            'planning_plugins': ['ompl_interface/OMPLPlanner'],
            'request_adapters': [
                'default_planning_request_adapters/ResolveConstraintFrames',
                'default_planning_request_adapters/ValidateWorkspaceBounds',
                'default_planning_request_adapters/CheckStartStateBounds',
                'default_planning_request_adapters/CheckStartStateCollision',
            ],
            'response_adapters': [
                'default_planning_response_adapters/AddTimeOptimalParameterization',
                'default_planning_response_adapters/ValidateSolution',
                'default_planning_response_adapters/DisplayMotionPath',
            ],
        },
    }

    # move_group 节点
    move_group_node = Node(
        package='moveit_ros_move_group',
        executable='move_group',
        output='screen',
        parameters=[moveit_config],
        arguments=['--ros-args', '--log-level', 'info'],
    )

    # RViz2 节点
    rviz_config_file = PathJoinSubstitution([
        FindPackageShare('robot_home_description'),
        'rviz',
        'robot_description.rviz'
    ])

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2_moveit',
        output='screen',
        arguments=['-d', rviz_config_file],
        parameters=[{
            'robot_description': robot_description,
            'robot_description_semantic': robot_description_semantic,
        }],
    )

    # robot_state_publisher 节点
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

    return LaunchDescription([
        robot_state_publisher_node,
        move_group_node,
        rviz_node,
    ])
