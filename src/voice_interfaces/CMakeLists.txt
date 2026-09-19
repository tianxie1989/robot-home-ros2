cmake_minimum_required(VERSION 3.8)
project(voice_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/SpeechRecognitionResult.msg"
  "srv/Speak.srv"
  "srv/Listen.srv"
  DEPENDENCIES std_msgs builtin_interfaces
)

ament_package()
