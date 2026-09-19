# robot-home-ros2

家用机器人 ROS2 工作空间 —— 涵盖移动底盘导航、机械臂控制、视觉检测、语音交互与任务规划的完整功能包集合。

A ROS2 workspace for a home robot: differential-drive navigation (SLAM/Nav2),
6-DOF arm control (MoveIt2), YOLO vision detection, voice interaction
(ASR / TTS / LLM), and task planning & household skills.

## Packages (`src/`)

| Package | Description |
| ------- | ----------- |
| `navigation_chassis` | SLAM 建图、Nav2 导航、避障 —— 机器人底盘控制 |
| `arm_control` | MoveIt2 机械臂控制:6DOF 运动规划、轨迹控制、抓取放置 |
| `vision_detection` | 物品识别与目标检测:YOLO 推理、摄像头驱动、深度处理 |
| `vision_interfaces` | 视觉检测自定义消息与服务接口 |
| `voice_interaction` | 语音交互:sherpa-onnx 流式 ASR、Piper TTS、Ollama LLM 对话 |
| `voice_interfaces` | 语音交互消息与服务接口 |
| `task_planner` | 任务规划与行为调度:语音指令解析、任务分解、行为树执行与技能调度 |
| `task_interfaces` | 任务消息、服务与动作接口(任务状态、抓取放置、区域整理等) |
| `robot_home_skills` | 家务技能库:捡玩具、物品归类、叠衣服等 |
| `robot_home_description` | URDF 模型描述:底盘、机械臂、夹爪、传感器 |
| `robot_home_bringup` | 系统启动与硬件接口 |
| `simulation_world` | Gazebo 家庭仿真场景(客厅、家具模型等) |
| `ai_training_bridge` | AI 训练服务器通信桥接:模型同步、数据采集、MQTT 通信 |

## Build

```bash
cd ros2_ws
rosdep install --from-paths src --ignore-src -r -y   # install dependencies
colcon build --symlink-install
source install/setup.bash
```

## Model weights (not committed)

Large model files are excluded via `.gitignore` (`*.onnx`, `*.pt`, ...).
After cloning, download/place the required weights manually, e.g.:

- `src/vision_detection/vision_detection/models/yolov8n.onnx`
  — export from [ultralytics YOLOv8n](https://github.com/ultralytics/ultralytics):
  `yolo export model=yolov8n.pt format=onnx`
- Voice model dirs for sherpa-onnx (ASR) and Piper (TTS) — see each node's config
  under `src/voice_interaction/config/`.

## Notes

- `build/`, `install/`, `log/` are colcon artifacts and are intentionally ignored.
- Interfaces packages (`*_interfaces`) should be built before the packages that
  depend on their generated messages.

## License

MIT
