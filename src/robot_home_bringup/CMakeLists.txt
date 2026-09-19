cmake_minimum_required(VERSION 3.8)
project(robot_home_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  launch
  config
  scripts
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/check_system.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
