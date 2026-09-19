cmake_minimum_required(VERSION 3.8)
project(robot_home_description)

find_package(ament_cmake REQUIRED)

# 安装URDF模型文件
install(DIRECTORY
  urdf
  meshes
  config
  launch
  rviz
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
