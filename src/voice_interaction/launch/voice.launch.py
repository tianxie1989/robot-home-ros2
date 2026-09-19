"""
语音交互启动文件
voice_interaction/launch/voice.launch.py

启动 TTS、ASR 和对话管理节点（含 LLM 对话能力：本地 Ollama）

注意：dialog_manager 的 Node(name=...) 必须与 config/llm_config.yaml 的顶层键一致，
否则 YAML 里的参数会被静默忽略。
"""

from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_share = FindPackageShare('voice_interaction')

    tts_config = PathJoinSubstitution([
        pkg_share, 'config', 'tts_config.yaml'
    ])

    asr_config = PathJoinSubstitution([
        pkg_share, 'config', 'asr_config.yaml'
    ])

    llm_config = PathJoinSubstitution([
        pkg_share, 'config', 'llm_config.yaml'
    ])

    # TTS 节点（Piper TTS）
    tts_node = Node(
        package='voice_interaction',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[tts_config],
    )

    # ASR 节点（sherpa-onnx 流式识别）
    asr_node = Node(
        package='voice_interaction',
        executable='audio_driver',
        name='asr_node',
        output='screen',
        parameters=[asr_config],
    )

    # 对话管理节点（正则命令 + Ollama LLM 开放对话）
    dialog_manager_node = Node(
        package='voice_interaction',
        executable='dialog_manager',
        name='dialog_manager',
        output='screen',
        parameters=[llm_config],
    )

    return LaunchDescription([
        tts_node,
        asr_node,
        dialog_manager_node,
    ])
