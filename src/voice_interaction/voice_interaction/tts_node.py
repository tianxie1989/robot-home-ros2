"""
语音合成节点 (TTS)
voice_interaction/voice_interaction/tts_node.py

使用 Piper TTS 引擎进行中文语音合成，合成 WAV 后通过 aplay 或 sounddevice 播放。
若 Piper 不可用，回退到 sherpa-onnx TTS，最终回退到打印输出模式。
"""

import io
import os
import wave
import tempfile
import subprocess
import threading
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TTSNode(Node):
    """语音合成节点 - Piper TTS / sherpa-onnx TTS / 打印模式"""

    def __init__(self):
        super().__init__('tts_node')

        # ==================== 参数声明 ====================
        self.declare_parameter('engine_type', 'piper')  # 'piper' / 'sherpa_onnx' / 'print'
        self.declare_parameter('model_path', '')         # Piper 模型路径
        self.declare_parameter('config_path', '')        # Piper 配置文件路径（可选）
        self.declare_parameter('output_device', '')      # 播放设备（空=默认）
        self.declare_parameter('speed', 1.0)             # 语速
        self.declare_parameter('volume', 0.9)            # 音量
        self.declare_parameter('enable_prompt_tones', True)  # 是否启用状态提示音

        self._engine_type = self.get_parameter('engine_type').value
        self._model_path = self.get_parameter('model_path').value
        self._config_path = self.get_parameter('config_path').value
        self._output_device = self.get_parameter('output_device').value or None
        self._speed = self.get_parameter('speed').value
        self._volume = self.get_parameter('volume').value
        self._enable_prompt_tones = self.get_parameter('enable_prompt_tones').value

        # ==================== TTS 引擎 ====================
        self._piper_voice = None       # Piper 语音对象
        self._sherpa_tts = None        # sherpa-onnx TTS 对象
        self._playback_lock = threading.Lock()  # 播放互斥锁

        self._init_engine()

        # ==================== ROS2 话题 ====================
        # 订阅语音合成请求
        self.speak_sub = self.create_subscription(
            String, '/voice/speak_text', self.speak_callback, 10)
        # 发布合成状态
        self.status_pub = self.create_publisher(
            String, '/voice/tts_status', 10)

        self._speaking = False

        self.get_logger().info(
            f'TTS 节点已启动 (引擎: {self._engine_type}, '
            f'语速: {self._speed}, 音量: {self._volume})'
        )

    # ================================================================
    #  引擎初始化
    # ================================================================
    def _init_engine(self):
        """按优先级初始化 TTS 引擎"""
        if self._engine_type == 'piper':
            if not self._init_piper():
                self.get_logger().warn('Piper 初始化失败，尝试 sherpa-onnx TTS')
                if not self._init_sherpa_tts():
                    self.get_logger().warn('sherpa-onnx TTS 也不可用，回退到打印模式')
                    self._engine_type = 'print'
        elif self._engine_type == 'sherpa_onnx':
            if not self._init_sherpa_tts():
                self.get_logger().warn('sherpa-onnx TTS 初始化失败，回退到打印模式')
                self._engine_type = 'print'
        else:
            self.get_logger().info('TTS 使用打印输出模式')

    def _init_piper(self) -> bool:
        """初始化 Piper TTS 引擎"""
        if not self._model_path:
            self.get_logger().warn('未配置 Piper 模型路径 (model_path)')
            return False

        if not os.path.exists(self._model_path):
            self.get_logger().warn(f'Piper 模型文件不存在: {self._model_path}')
            return False

        try:
            from piper import PiperVoice
            self._piper_voice = PiperVoice.load(self._model_path)
            self.get_logger().info(f'Piper TTS 加载成功: {self._model_path}')
            return True
        except ImportError:
            self.get_logger().warn('piper Python 包未安装')
            return False
        except Exception as e:
            self.get_logger().error(f'Piper TTS 加载异常: {e}')
            return False
    def _init_sherpa_tts(self) -> bool:
        """初始化 sherpa-onnx TTS（备选方案）"""
        try:
            import sherpa_onnx
            # 需要配置 VITS 模型
            if not self._model_path:
                self.get_logger().warn('未配置模型路径，sherpa-onnx TTS 不可用')
                return False

            tts_config = sherpa_onnx.OfflineTtsConfig()
            tts_config.model.vits.model = self._model_path
            tts_config.model.vits.lexicon = ''  # 根据实际模型配置
            tts_config.model.vits.tokens = os.path.join(
                os.path.dirname(self._model_path), 'tokens.txt')
            self._sherpa_tts = sherpa_onnx.OfflineTts(tts_config)
            self._engine_type = 'sherpa_onnx'
            self.get_logger().info('sherpa-onnx TTS 初始化成功')
            return True
        except ImportError:
            self.get_logger().warn('sherpa-onnx 未安装，TTS 备选方案不可用')
            return False
        except Exception as e:
            self.get_logger().error(f'sherpa-onnx TTS 初始化异常: {e}')
            return False

    # ================================================================
    #  语音合成 & 播放
    # ================================================================
    def speak_callback(self, msg: String):
        """处理语音合成请求"""
        text = msg.data.strip()
        if not text:
            return

        self.get_logger().info(f'TTS 请求: "{text}"')

        if self._speaking:
            self.get_logger().warn('正在说话中，排队等待...')

        self._speaking = True
        self._publish_status('speaking')

        try:
            self._speak(text)
        except Exception as e:
            self.get_logger().error(f'TTS 执行失败: {e}')
        finally:
            self._speaking = False
            self._publish_status('idle')

    def _speak(self, text: str):
        """执行语音合成与播放"""
        if self._engine_type == 'piper' and self._piper_voice is not None:
            self._speak_piper(text)
        elif self._engine_type == 'sherpa_onnx' and self._sherpa_tts is not None:
            self._speak_sherpa(text)
        else:
            # 打印输出模式
            self.get_logger().info(f'[TTS 输出] 🔊 {text}')
            print(f'🔊 {text}')

    def _speak_piper(self, text: str):
        """使用 Piper 合成并播放"""
        with self._playback_lock:
            # 合成音频块
            chunks = list(self._piper_voice.synthesize(text))
            if not chunks:
                self.get_logger().warn('Piper 合成无音频输出')
                return

            # 拼接所有音频块
            total_audio = b''
            sample_rate = 22050
            for c in chunks:
                total_audio += c.audio_int16_bytes
                sample_rate = c.sample_rate

            # 写入临时 WAV 文件
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix='.wav', delete=False, dir=tempfile.gettempdir()
                ) as f:
                    tmp_path = f.name
                    with wave.open(f, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(total_audio)

                # 播放 TTS 音频前：先播放“AI回复”提示音(440Hz, 0.2s)
                self._play_prompt_tone()
                self._play_wav(tmp_path)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

    def _speak_sherpa(self, text: str):
        """使用 sherpa-onnx TTS 合成并播放"""
        with self._playback_lock:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix='.wav', delete=False, dir=tempfile.gettempdir()
                ) as f:
                    tmp_path = f.name

                self._sherpa_tts.generate(text, 0, tmp_path)
                # 播放 TTS 音频前：先播放“AI回复”提示音(440Hz, 0.2s)
                self._play_prompt_tone()
                self._play_wav(tmp_path)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

    def _play_prompt_tone(self):
        """播放“AI回复”提示音（440Hz, 0.2s，低音），同步阻塞以确保在 TTS 音频之前"""
        if not self._enable_prompt_tones:
            return
        self._play_beep(freq=440, duration=0.2, volume=0.4, wait=True)

    def _play_beep(self, freq=440, duration=0.2, volume=0.4, wait=True):
        """生成正弦波提示音并通过 paplay 播放（走 PipeWire → 蓝牙音响）"""
        if not self._enable_prompt_tones:
            return
        tmp_path = None
        try:
            sample_rate = 22050
            n = int(sample_rate * duration)
            t = np.linspace(0, duration, n, dtype=np.float32)
            # 淡入淡出避免爆音
            fade = min(0.01, duration / 4.0)
            envelope = np.minimum(t / fade, 1.0) * \
                np.minimum((duration - t) / fade, 1.0)
            tone = (volume * envelope *
                    np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)

            with tempfile.NamedTemporaryFile(
                suffix='.wav', delete=False, dir=tempfile.gettempdir()
            ) as f:
                tmp_path = f.name
                with wave.open(f, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(tone.tobytes())

            if wait:
                subprocess.run(
                    ['paplay', tmp_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(
                    ['paplay', tmp_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                tmp_path = None  # 异步播放时不立即删除，交由系统临时目录回收
        except Exception as e:
            self.get_logger().debug(f'播放提示音失败: {e}')
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _play_wav(self, wav_path: str):
        """播放 WAV 文件，优先使用 paplay（PipeWire/蓝牙），备选 aplay"""
        # 尝试 paplay（PipeWire PulseAudio 兼容，支持蓝牙音响）
        try:
            subprocess.run(['paplay', wav_path], timeout=30, check=True)
            return
        except FileNotFoundError:
            self.get_logger().debug('paplay 不可用，尝试 aplay')
        except subprocess.TimeoutExpired:
            self.get_logger().warn('paplay 播放超时')
            return
        except Exception as e:
            self.get_logger().debug(f'paplay 播放失败: {e}')

        # 备选: aplay（ALSA 直连，不支持蓝牙）
        try:
            cmd = ['aplay', '-q', wav_path]
            if self._output_device:
                cmd.extend(['-D', self._output_device])
            subprocess.run(cmd, timeout=30, check=True)
            return
        except Exception as e:
            self.get_logger().debug(f'aplay 播放失败: {e}')

        self.get_logger().warn(f'无可用播放设备，仅打印文本: {wav_path}')

    # ================================================================
    #  发布方法
    # ================================================================
    def _publish_status(self, status: str):
        """发布 TTS 状态"""
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    # ================================================================
    #  资源清理
    # ================================================================
    def destroy_node(self):
        """清理 TTS 引擎"""
        self._piper_voice = None
        self._sherpa_tts = None
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TTSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('TTS 节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
