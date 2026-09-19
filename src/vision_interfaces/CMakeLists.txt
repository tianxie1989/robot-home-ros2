cmake_minimum_required(VERSION 3.8)
project(vision_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/DetectedObject.msg"
  "msg/DetectedObjectArray.msg"
  "msg/ObjectPose3D.msg"
  "srv/DetectObjects.srv"
  "srv/ClassifyObject.srv"
  DEPENDENCIES std_msgs geometry_msgs sensor_msgs
)

ament_package()
