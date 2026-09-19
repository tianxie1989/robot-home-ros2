"""视觉检测启动文件"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('vision_detection')
    camera_params = os.path.join(pkg_share, 'config', 'camera_params.yaml')
    detection_params = os.path.join(pkg_share, 'config', 'detection.yaml')

    camera_driver = Node(
        package='vision_detection',
        executable='camera_driver',
        name='camera_driver',
        parameters=[camera_params],
        output='screen',
    )

    object_detector = Node(
        package='vision_detection',
        executable='object_detector',
        name='object_detector',
        parameters=[detection_params],
        output='screen',
    )

    depth_processor = Node(
        package='vision_detection',
        executable='depth_processor',
        name='depth_processor',
        output='screen',
    )

    object_tracker = Node(
        package='vision_detection',
        executable='object_tracker',
        name='object_tracker',
        output='screen',
    )

    return LaunchDescription([
        camera_driver,
        object_detector,
        depth_processor,
        object_tracker,
    ])
