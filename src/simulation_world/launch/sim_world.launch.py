"""
仿真世界启动文件
simulation_world/launch/sim_world.launch.py

启动 Gazebo 并加载客厅仿真世界，同时加载机器人模型
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    SetEnvironmentVariable,
)
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, Command
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # 包路径
    sim_world_pkg = FindPackageShare('simulation_world')
    description_pkg = FindPackageShare('robot_home_description')

    # 世界文件
    world_file = PathJoinSubstitution([
        sim_world_pkg, 'worlds', 'living_room.world'
    ])

    # Gazebo 参数
    gazebo_params = PathJoinSubstitution([
        sim_world_pkg, 'config', 'gazebo_params.yaml'
    ])

    # 机器人 URDF
    robot_urdf_xacro = PathJoinSubstitution([
        description_pkg, 'urdf', 'robot_home.urdf.xacro'
    ])
    robot_description = Command(['xacro ', robot_urdf_xacro])

    # 设置 Gazebo 模型路径
    gazebo_model_path = os.path.join(
        get_package_share_directory('simulation_world'), 'models'
    )

    set_gazebo_model_path = SetEnvironmentVariable(
        'GAZEBO_MODEL_PATH',
        [LaunchConfiguration('GAZEBO_MODEL_PATH', default=''), ':', gazebo_model_path]
    )

    # 启动 Gazebo 服务器和客户端
    gazebo = IncludeLaunchDescription(
        os.path.join(
            get_package_share_directory('gazebo_ros'),
            'launch',
            'gazebo.launch.py',
        ),
        launch_arguments={
            'world': world_file,
            'verbose': 'true',
        }.items(),
    )

    # robot_state_publisher
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': robot_description,
            'publish_frequency': 50.0,
        }],
    )

    # 在 Gazebo 中生成机器人
    spawn_robot = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        name='spawn_robot',
        output='screen',
        arguments=[
            '-topic', 'robot_description',
            '-entity', 'robot_home',
            '-x', '0.0',
            '-y', '0.0',
            '-z', '0.1',
        ],
    )

    return LaunchDescription([
        set_gazebo_model_path,
        gazebo,
        robot_state_publisher,
        spawn_robot,
    ])
