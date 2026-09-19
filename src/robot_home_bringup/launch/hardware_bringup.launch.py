"""真实硬件启动
启动 robot_state_publisher + 所有底层硬件驱动
需要同时 source robot_home 工作空间和 driver 工作空间
"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    bringup_pkg = get_package_share_directory('robot_home_bringup')
    desc_pkg = get_package_share_directory('robot_home_description')

    # ----------------------------------------------------------------
    # Launch Arguments
    # ----------------------------------------------------------------
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    config_path = LaunchConfiguration(
        'config_path',
        default=os.path.join(bringup_pkg, '..', '..', 'config', 'common_params.yaml'),
    )

    # ----------------------------------------------------------------
    # 1. 机器人状态发布 (robot_home_description)
    # ----------------------------------------------------------------
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(desc_pkg, 'launch', 'robot_state_publisher.launch.py')
        ),
        launch_arguments={'use_sim_time': use_sim_time}.items(),
    )

    # ----------------------------------------------------------------
    # 2. 所有硬件驱动 (driver_bringup)
    #    driver_bringup 的 all_drivers.launch.py 会启动:
    #      - IMU, 电机控制, 编码器里程计, 相机驱动, TOF传感器, Web流
    #    注意: all_drivers.launch.py 自带 robot_state_publisher,
    #    这里通过 driver_bringup 包是否存在来决定是否 include
    # ----------------------------------------------------------------
    try:
        driver_bringup_pkg = get_package_share_directory('driver_bringup')
        all_drivers_launch = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(driver_bringup_pkg, 'launch', 'all_drivers.launch.py')
            ),
            launch_arguments={
                'use_robot_state_publisher': 'false',
                'config_path': config_path,
                'use_web_streamer': 'true',
            }.items(),
        )
        has_driver_bringup = True
    except Exception:
        has_driver_bringup = False

    ld = LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'config_path',
            default_value=os.path.join(
                bringup_pkg, '..', '..', 'config', 'common_params.yaml'
            ),
            description='common_params.yaml 的绝对路径',
        ),
        rsp_launch,
    ])

    if has_driver_bringup:
        ld.add_action(all_drivers_launch)
    else:
        ld.add_action(LogInfo(
            msg='[hardware_bringup] driver_bringup 包未找到，'
                '请 source driver 工作空间以启动硬件驱动。'
        ))

    return ld
