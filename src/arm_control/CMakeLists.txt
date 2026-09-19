cmake_minimum_required(VERSION 3.8)
project(arm_control)

find_package(ament_cmake REQUIRED)

# Install config files
install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

# Install launch files
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install MoveIt config files
install(DIRECTORY moveit_config/
  DESTINATION share/${PROJECT_NAME}/moveit_config
)

# Install scripts
install(PROGRAMS
  scripts/pick_place_demo.py
  scripts/arm_teleop.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
