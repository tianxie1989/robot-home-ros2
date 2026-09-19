"""在RViz2中查看机器人模型"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('robot_home_description')
    rviz_config = os.path.join(pkg_share, 'rviz', 'robot_description.rviz')

    # 包含 robot_state_publisher
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_share, 'launch', 'robot_state_publisher.launch.py')
        )
    )

    # RViz2节点
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config],
        output='screen',
    )

    # 关节状态发布器GUI（方便手动调整关节角度查看模型）
    jsp_gui_node = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        name='joint_state_publisher_gui',
    )

    return LaunchDescription([
        rsp_launch,
        jsp_gui_node,
        rviz_node,
    ])
