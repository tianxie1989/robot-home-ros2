#!/usr/bin/env python3
"""系统健康检查脚本 - 检测ROS2环境和硬件状态"""
import subprocess
import sys


def check_ros2():
    """检查ROS2环境"""
    print("[检查] ROS2环境...")
    try:
        result = subprocess.run(['ros2', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"  ✓ ROS2: {result.stdout.strip()}")
            return True
        else:
            print("  ✗ ROS2未正确安装")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  ✗ ROS2命令未找到或超时")
        return False


def check_packages():
    """检查必要的ROS2包"""
    print("[检查] 必要的ROS2包...")
    required = [
        'robot_home_description',
        'robot_home_bringup',
        'vision_detection',
        'navigation_chassis',
        'arm_control',
        'voice_interaction',
        'task_planner',
    ]
    all_ok = True
    for pkg in required:
        try:
            result = subprocess.run(
                ['ros2', 'pkg', 'prefix', pkg],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print(f"  ✓ {pkg}")
            else:
                print(f"  ✗ {pkg} (未找到)")
                all_ok = False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"  ✗ {pkg} (检查失败)")
            all_ok = False
    return all_ok


def check_topics():
    """检查活跃的ROS2 topic"""
    print("[检查] 活跃的ROS2 Topics...")
    try:
        result = subprocess.run(
            ['ros2', 'topic', 'list'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            topics = result.stdout.strip().split('\n')
            print(f"  当前活跃Topic数: {len(topics)}")
            for t in topics[:10]:
                print(f"    {t}")
            return True
        else:
            print("  ⚠ 无法列出Topic")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  ⚠ ROS2节点未运行")
        return False


def main():
    print("=" * 50)
    print("  家用机器人 - 系统健康检查")
    print("=" * 50)
    print()

    results = []
    results.append(check_ros2())
    results.append(check_packages())
    results.append(check_topics())

    print()
    print("=" * 50)
    if all(results):
        print("  ✓ 所有检查通过")
        sys.exit(0)
    else:
        print("  ⚠ 部分检查未通过，请检查环境配置")
        sys.exit(1)


if __name__ == '__main__':
    main()
