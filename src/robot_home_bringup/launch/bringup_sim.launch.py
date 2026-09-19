"""仿真模式启动 - Gazebo + 机器人"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    desc_pkg = get_package_share_directory('robot_home_description')
    sim_pkg = get_package_share_directory('simulation_world')

    # 机器人状态发布（仿真时间）
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(desc_pkg, 'launch', 'robot_state_publisher.launch.py')
        ),
        launch_arguments={'use_sim_time': 'true'}.items(),
    )

    # Gazebo仿真世界
    sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(sim_pkg, 'launch', 'sim_world.launch.py')
        ),
    )

    return LaunchDescription([
        rsp_launch,
        sim_launch,
    ])
