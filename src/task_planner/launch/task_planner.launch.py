"""
任务规划器启动文件
task_planner/launch/task_planner.launch.py

启动任务管理节点和行为树引擎
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('task_planner')

    task_config = PathJoinSubstitution([
        pkg_share, 'config', 'task_config.yaml'
    ])

    task_manager_node = Node(
        package='task_planner',
        executable='task_manager',
        name='task_manager',
        output='screen',
        parameters=[task_config],
    )

    return LaunchDescription([
        task_manager_node,
    ])
