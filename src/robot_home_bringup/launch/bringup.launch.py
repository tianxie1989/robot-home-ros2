"""机器人总启动文件 - 启动所有核心节点"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    bringup_pkg = get_package_share_directory('robot_home_bringup')
    desc_pkg = get_package_share_directory('robot_home_description')

    use_sim_time = LaunchConfiguration('use_sim_time', default='false')

    # 机器人状态发布
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(desc_pkg, 'launch', 'robot_state_publisher.launch.py')
        ),
        launch_arguments={'use_sim_time': use_sim_time}.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        rsp_launch,
        # TODO: 后续逐步添加各子系统launch
        # vision_launch,
        # navigation_launch,
        # arm_launch,
        # voice_launch,
        # task_planner_launch,
    ])
