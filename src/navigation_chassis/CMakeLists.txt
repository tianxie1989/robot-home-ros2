cmake_minimum_required(VERSION 3.8)
project(navigation_chassis)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  launch
  config
  maps
  behavior_trees
  scripts
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/teleop_keyboard.py
  scripts/waypoint_manager.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
