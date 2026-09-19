"""
语音识别节点 (ASR)
voice_interaction/voice_interaction/asr_node.py

使用 sherpa-onnx 流式中文语音识别引擎，parec (PipeWire) 进行麦克风录音。
支持蓝牙/USB/内置麦克风，自动检测说话开始/结束 (VAD)。
若 sherpa-onnx 不可用，回退到键盘模拟输入模式。
"""

import os
import re
import time
import wave
import queue
import difflib
import tempfile
import threading
import subprocess
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# ==================== 唤醒词对话状态机 ====================
STATE_IDLE = 'idle'      # 待机：持续录音识别，但只对唤醒词作出反应
STATE_ACTIVE = 'active'  # 对话：正常识别并发布结果，支持退出命令/超时
STATE_TTS = 'tts'        # TTS 播放中：暂停录音（作为覆盖在 IDLE/ACTIVE 之上的
                         # 瞬时暂停态，由 self._tts_playing 标志驱动，播放结束
                         # 后自动回到之前的 IDLE/ACTIVE 状态）


class ASRNode(Node):
    """语音识别节点 - sherpa-onnx 流式识别 / 键盘模拟 + 唤醒词状态机"""

    def __init__(self):
        super().__init__('asr_node')

        # ==================== 参数声明 ====================
        self.declare_parameter('engine', 'sherpa_onnx')
        self.declare_parameter('input_mode', 'microphone')  # 'microphone' 或 'keyboard'
        self.declare_parameter('model_dir', '')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('audio_device', '')  # 空字符串=默认设备
        self.declare_parameter('vad_enabled', True)
        self.declare_parameter('silence_timeout', 2.0)
        self.declare_parameter('enable_prompt_tones', True)  # 是否启用状态提示音

        # ---------- 唤醒词对话模式参数 ----------
        # 唤醒词列表：待机模式下匹配到才进入对话
        self.declare_parameter(
            'wake_words', ['小机器人', '你好机器人', '小智小智'])
        # 退出命令列表：对话模式下匹配到则返回待机
        self.declare_parameter(
            'exit_commands', ['结束对话', '再见', '退出', '关闭对话'])
        # 对话模式无语音超时（秒），超时自动返回待机
        self.declare_parameter('active_timeout', 30.0)
        # 唤醒词是否启用模糊匹配（容忍 ASR 识别错字）
        self.declare_parameter('wake_word_fuzzy', True)

        self._engine_type = self.get_parameter('engine').value
        self._input_mode = self.get_parameter('input_mode').value
        self._model_dir = self.get_parameter('model_dir').value
        self._sample_rate = self.get_parameter('sample_rate').value
        self._audio_device = self.get_parameter('audio_device').value or None
        self._vad_enabled = self.get_parameter('vad_enabled').value
        self._silence_timeout = self.get_parameter('silence_timeout').value
        self._enable_prompt_tones = self.get_parameter('enable_prompt_tones').value

        self._wake_words = list(self.get_parameter('wake_words').value or [])
        self._exit_commands = list(self.get_parameter('exit_commands').value or [])
        self._active_timeout = float(self.get_parameter('active_timeout').value)
        self._wake_word_fuzzy = bool(self.get_parameter('wake_word_fuzzy').value)

        # 可选：拼音模糊匹配（处理同音错字，如“志”↔“智”）；未安装则自动跳过
        try:
            from pypinyin import lazy_pinyin
            self._lazy_pinyin = lazy_pinyin
        except Exception:
            self._lazy_pinyin = None

        # ==================== 识别器 & 音频 ====================
        self._recognizer = None       # sherpa-onnx 流式识别器
        self._arecord_proc = None     # arecord 子进程
        self._audio_queue = queue.Queue()
        self._running = False         # 麦克风录音循环控制标志

        # 初始化识别引擎
        self._init_engine()

        # ==================== ROS2 话题 ====================
        # 发布识别结果
        self.result_pub = self.create_publisher(
            String, '/voice/recognition_text', 10)
        # 发布识别状态
        self.status_pub = self.create_publisher(
            String, '/voice/asr_status', 10)
        # 订阅开始识别指令
        self.listen_sub = self.create_subscription(
            String, '/voice/listen_start', self.listen_callback, 10)
        # 订阅 TTS 播放状态：TTS 播放时暂停录音，解决回声反馈自问自答
        self.tts_status_sub = self.create_subscription(
            String, '/voice/tts_status', self.tts_status_callback, 10)

        # ==================== 运行状态 ====================
        self._listening = False
        # ---------- 唤醒词对话状态机 ----------
        self._state = STATE_IDLE                  # 当前对话状态
        self._tts_playing = False                 # TTS 播放中标志（暂停录音）
        self._paused_reset_done = False           # TTS 暂停期间是否已重置识别流
        self._last_active_time = time.monotonic() # ACTIVE 模式最近一次语音时间

        self.get_logger().info(
            f'ASR 节点已启动 (引擎: {self._engine_type}, '
            f'输入模式: {self._input_mode}, '
            f'VAD: {"开" if self._vad_enabled else "关"})'
        )
        self.get_logger().info(
            f'唤醒词模式已启用 | 唤醒词: {self._wake_words} | '
            f'退出命令: {self._exit_commands} | '
            f'超时: {self._active_timeout:.0f}s | '
            f'模糊匹配: {"开" if self._wake_word_fuzzy else "关"}'
        )

        # 键盘模式：启动输入线程
        if self._input_mode == 'keyboard':
            self._input_thread = threading.Thread(
                target=self._keyboard_input_loop, daemon=True)
            self._input_thread.start()
        elif self._input_mode == 'microphone' and self._recognizer is not None:
            # 麦克风模式且引擎就绪 → 启动持续录音线程
            self._running = True
            self._mic_thread = threading.Thread(
                target=self._microphone_loop, daemon=True)
            self._mic_thread.start()

    # ================================================================
    #  引擎初始化
    # ================================================================
    def _init_engine(self):
        """初始化 sherpa-onnx 流式识别器"""
        if self._input_mode != 'microphone':
            self.get_logger().info('当前为键盘输入模式，跳过引擎初始化')
            return

        if not self._model_dir:
            self.get_logger().warn(
                '未配置 model_dir，麦克风模式不可用，回退到键盘模式')
            self._input_mode = 'keyboard'
            return

        try:
            import sherpa_onnx
            import os

            # 尝试多种工厂方法创建识别器
            model_path = os.path.join(self._model_dir, 'model.int8.onnx')
            tokens_path = os.path.join(self._model_dir, 'tokens.txt')

            recognizer = None

            # 方法1: from_paraformer（Zipformer/Paraformer 流式模型）
            if hasattr(sherpa_onnx, 'OnlineRecognizer'):
                rec_cls = sherpa_onnx.OnlineRecognizer
                if hasattr(rec_cls, 'from_paraformer'):
                    try:
                        recognizer = rec_cls.from_paraformer(
                            paraformer=model_path,
                            tokens=tokens_path,
                            num_threads=2,
                            sample_rate=self._sample_rate,
                            feature_dim=80,
                            enable_endpoint_detection=self._vad_enabled,
                            rule1_min_trailing_silence=self._silence_timeout,
                            rule2_min_trailing_silence=self._silence_timeout / 2,
                            rule3_min_utterance_length=20,
                        )
                        self.get_logger().info('使用 from_paraformer 创建识别器成功')
                    except Exception as e:
                        self.get_logger().warn(f'from_paraformer 失败: {e}')

                # 方法2: from_transducer
                if recognizer is None and hasattr(rec_cls, 'from_transducer'):
                    try:
                        # transducer 模型需要 encoder/decoder/joiner 三个文件
                        # 尝试多种文件名格式
                        encoder_names = [
                            'encoder-epoch-99-avg-1.int8.onnx',
                            'encoder-epoch-30-avg-10.int8.onnx',
                            'encoder.int8.onnx',
                        ]
                        decoder_names = [
                            'decoder-epoch-99-avg-1.int8.onnx',
                            'decoder-epoch-30-avg-10.int8.onnx',
                            'decoder.int8.onnx',
                        ]
                        joiner_names = [
                            'joiner-epoch-99-avg-1.int8.onnx',
                            'joiner-epoch-30-avg-10.int8.onnx',
                            'joiner.int8.onnx',
                        ]
                        encoder = decoder = joiner = None
                        for name in encoder_names:
                            p = os.path.join(self._model_dir, name)
                            if os.path.exists(p):
                                encoder = p
                                break
                        for name in decoder_names:
                            p = os.path.join(self._model_dir, name)
                            if os.path.exists(p):
                                decoder = p
                                break
                        for name in joiner_names:
                            p = os.path.join(self._model_dir, name)
                            if os.path.exists(p):
                                joiner = p
                                break
                        if encoder and decoder and joiner:
                            recognizer = rec_cls.from_transducer(
                                encoder=encoder,
                                decoder=decoder,
                                joiner=joiner,
                                tokens=tokens_path,
                                num_threads=2,
                                sample_rate=self._sample_rate,
                                feature_dim=80,
                                enable_endpoint_detection=self._vad_enabled,
                                rule1_min_trailing_silence=self._silence_timeout,
                                rule2_min_trailing_silence=self._silence_timeout / 2,
                                rule3_min_utterance_length=20,
                            )
                            self.get_logger().info('使用 from_transducer 创建识别器成功')
                        else:
                            self.get_logger().warn(f'未找到完整的 transducer 模型文件 (enc={encoder}, dec={decoder}, join={joiner})')
                    except Exception as e:
                        self.get_logger().warn(f'from_transducer 失败: {e}')

                # 方法3: 通用构造函数 (OnlineRecognizer + OnlineRecognizerConfig)
                if recognizer is None and hasattr(sherpa_onnx, 'OnlineRecognizerConfig'):
                    try:
                        config = sherpa_onnx.OnlineRecognizerConfig()
                        config.sherpa_onnx_feat_config.feat_config.sampling_rate = self._sample_rate
                        config.sherpa_onnx_feat_config.feat_config.feature_dim = 80
                        config.model_config.num_threads = 2
                        config.model_config.tokens = tokens_path
                        config.model_config.transducer.encoder = os.path.join(
                            self._model_dir, 'encoder-epoch-99-avg-1.int8.onnx')
                        config.model_config.transducer.decoder = os.path.join(
                            self._model_dir, 'decoder-epoch-99-avg-1.int8.onnx')
                        config.model_config.transducer.joiner = os.path.join(
                            self._model_dir, 'joiner-epoch-99-avg-1.int8.onnx')
                        config.enable_endpoint = self._vad_enabled
                        config.rule1_min_trailing_silence = self._silence_timeout
                        config.rule2_min_trailing_silence = self._silence_timeout / 2
                        config.rule3_min_utterance_length = 20
                        recognizer = sherpa_onnx.OnlineRecognizer(config)
                        self.get_logger().info('使用 OnlineRecognizerConfig 创建识别器成功')
                    except Exception as e:
                        self.get_logger().warn(f'OnlineRecognizerConfig 方式失败: {e}')

            if recognizer is not None:
                self._recognizer = recognizer
                self.get_logger().info(f'sherpa-onnx 识别器加载成功 (模型目录: {self._model_dir})')
            else:
                self.get_logger().error(
                    '所有 sherpa-onnx 工厂方法均失败，回退到键盘模式')
                self._input_mode = 'keyboard'

        except ImportError:
            self.get_logger().warn(
                'sherpa-onnx 未安装，回退到键盘模拟输入模式')
            self._input_mode = 'keyboard'
        except Exception as e:
            self.get_logger().error(f'sherpa-onnx 初始化异常: {e}')
            self._input_mode = 'keyboard'

    # ================================================================
    #  状态提示音
    # ================================================================
    def _play_beep(self, freq=880, duration=0.15, volume=0.4,
                   repeat=1, gap=0.08, wait=False):
        """生成正弦波提示音并通过 paplay 播放（走 PipeWire → 蓝牙音响）

        :param freq: 频率 (Hz)
        :param duration: 单声时长 (秒)
        :param volume: 音量 (0.0~1.0)
        :param repeat: 重复次数（多声合并到同一个 WAV，避免异步重叠）
        :param gap: 多声之间的静音间隔 (秒)
        :param wait: True=同步阻塞播放(subprocess.run)，False=异步(Popen)
        """
        if not self._enable_prompt_tones:
            return
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

            # 拼接多声 beep（中间插入静音）
            if repeat > 1:
                silence = np.zeros(int(sample_rate * gap), dtype=np.int16)
                parts = []
                for i in range(repeat):
                    parts.append(tone)
                    if i < repeat - 1:
                        parts.append(silence)
                audio = np.concatenate(parts)
            else:
                audio = tone

            total_dur = repeat * duration + max(0, repeat - 1) * gap

            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp.close()
            with wave.open(tmp.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio.tobytes())

            if wait:
                subprocess.run(
                    ['paplay', tmp.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._safe_unlink(tmp.name)
            else:
                subprocess.Popen(
                    ['paplay', tmp.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # 播放完成后延迟清理临时文件
                threading.Timer(
                    total_dur + 1.0, self._safe_unlink, args=[tmp.name]).start()
        except Exception as e:
            self.get_logger().debug(f'播放提示音失败: {e}')

    def _discard_audio(self, seconds=0.35):
        """排空录音缓冲，避免提示音被录入识别，同时为提示音播放留出时间"""
        # 未启用提示音时无需排空，避免丢弃真实语音
        if not self._enable_prompt_tones:
            return
        if self._arecord_proc is None or self._arecord_proc.stdout is None:
            return
        total_bytes = int(self._sample_rate * 2 * seconds)
        chunk = max(1, int(self._sample_rate * 2 * 0.1))
        read_bytes = 0
        try:
            while read_bytes < total_bytes:
                data = self._arecord_proc.stdout.read(
                    min(chunk, total_bytes - read_bytes))
                if not data:
                    break
                read_bytes += len(data)
        except Exception:
            pass

    @staticmethod
    def _safe_unlink(path):
        try:
            os.unlink(path)
        except Exception:
            pass

    # ================================================================
    #  麦克风录音 & 流式识别
    # ================================================================
    def _microphone_loop(self):
        """麦克风录音 + 流式识别主循环（使用 parec 子进程，支持蓝牙麦克风）"""
        # 构建 parec 命令（通过 PipeWire 录音，支持蓝牙/USB/内置麦克风）
        cmd = [
            'parec',
            '--format=s16le',
            f'--rate={self._sample_rate}',
            '--channels=1',
        ]
        # 如果指定了设备，添加 --device 参数
        if self._audio_device:
            cmd.append(f'--device={self._audio_device}')

        self.get_logger().info(
            f'麦克风录音已启动 (parec/PipeWire, 采样率: {self._sample_rate}Hz, '
            f'设备: {self._audio_device or "默认"})')
        self._publish_status('ready')

        # 启动 parec 子进程
        try:
            self._arecord_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=self._sample_rate * 2 // 10  # ~100ms 缓冲
            )
        except Exception as e:
            self.get_logger().error(f'启动 parec 失败: {e}')
            return

        # 创建流式识别流
        try:
            stream = self._recognizer.create_stream()
        except Exception as e:
            self.get_logger().error(f'创建识别流失败: {e}')
            self._arecord_proc.terminate()
            return

        last_text = ''
        segment_index = 0
        chunk_size = int(self._sample_rate * 0.1) * 2  # 100ms of int16 mono = 3200 bytes

        # 启动时排空缓冲，避免残留音频被误识别
        self._discard_audio(0.35)

        # 进入初始待机状态并发布
        self._set_state(STATE_IDLE, publish=True)
        self.get_logger().info('待机中：请说唤醒词（如“小机器人”）开始对话')

        while self._running and rclpy.ok():
            # 从 parec stdout 读取音频数据
            try:
                raw = self._arecord_proc.stdout.read(chunk_size)
                if not raw:
                    self.get_logger().warn('parec 输出结束，录音中断')
                    break
            except Exception as e:
                self.get_logger().debug(f'读取音频数据异常: {e}')
                continue

            # ---------- TTS 播放中：暂停识别，丢弃音频（防回声反馈）----------
            if self._tts_playing:
                if not self._paused_reset_done:
                    # 刚进入暂停：重置识别流，清空已累积的（含回声的）音频
                    try:
                        self._recognizer.reset(stream)
                    except Exception:
                        pass
                    last_text = ''
                    self._paused_reset_done = True
                # 仍持续读取并丢弃 chunk，保证 parec 管道不堵塞
                continue

            # ---------- 从 TTS 暂停恢复：先排空残留回声再继续识别 ----------
            if self._paused_reset_done:
                self._paused_reset_done = False
                self._discard_audio(0.30)
                # TTS 结束后刷新超时计时，给用户完整的应答时间窗口
                if self._state == STATE_ACTIVE:
                    self._last_active_time = time.monotonic()

            # ---------- ACTIVE 模式超时检测：无有效语音 → 返回待机 ----------
            if self._state == STATE_ACTIVE and \
                    (time.monotonic() - self._last_active_time) > self._active_timeout:
                self.get_logger().info(
                    f'对话超时（{self._active_timeout:.0f}s 无有效语音），返回待机')
                self._play_beep(freq=330, duration=0.15, repeat=2)  # 超时提示音
                self._set_state(STATE_IDLE, publish=True)
                self._discard_audio(0.35)
                continue

            # 将 raw bytes 转为 int16 numpy 数组
            audio_data = np.frombuffer(raw, dtype=np.int16)
            if len(audio_data) == 0:
                continue

            # 转为 float32 归一化到 [-1, 1]
            samples = audio_data.astype(np.float32) / 32768.0

            # 送入识别器
            stream.accept_waveform(self._sample_rate, samples)

            # 解码中间结果
            while self._recognizer.is_ready(stream):
                self._recognizer.decode_stream(stream)

            # 获取当前片段文本
            result = self._recognizer.get_result(stream)
            current_text = result.text.strip() if hasattr(result, 'text') else str(result).strip()

            if current_text and current_text != last_text:
                self.get_logger().debug(f'中间结果: "{current_text}"')

            # 检测端点（一句话结束）
            is_endpoint = self._recognizer.is_endpoint(stream)

            if is_endpoint and current_text:
                last_text = ''
                segment_index += 1
                self._recognizer.reset(stream)
                # 根据当前状态处理这句话（待机→查唤醒词；对话→发布/查退出）
                self._process_utterance(current_text)
                # 排空缓冲：让 beep 播完且不被录入，并为可能的 TTS 回声留出时间
                self._discard_audio(0.30)
            elif is_endpoint:
                self._recognizer.reset(stream)
            else:
                last_text = current_text

        # 清理
        if self._arecord_proc is not None:
            try:
                self._arecord_proc.terminate()
                self._arecord_proc.wait(timeout=3)
            except Exception:
                try:
                    self._arecord_proc.kill()
                except Exception:
                    pass

        self.get_logger().info('麦克风录音循环已退出')

    # ================================================================
    #  键盘模拟输入
    # ================================================================
    def _keyboard_input_loop(self):
        """键盘输入模拟循环"""
        self.get_logger().info(
            '键盘模拟输入模式: 输入文本后按 Enter 发送 (输入 q 退出)')
        while rclpy.ok():
            try:
                text = input('🎤 [模拟语音输入] > ')
                text = text.strip()
                if text.lower() == 'q':
                    break
                if text:
                    self._process_utterance(text)
            except EOFError:
                break
            except KeyboardInterrupt:
                break

    # ================================================================
    #  ROS2 回调
    # ================================================================
    def listen_callback(self, msg: String):
        """处理开始识别指令"""
        if self._listening:
            self.get_logger().warn('正在识别中，忽略重复指令')
            return
        self.get_logger().info('开始语音识别...')
        self._listening = True
        self._publish_status('listening')

    # ================================================================
    #  发布方法
    # ================================================================
    def _publish_result(self, text: str, confidence: float = 0.0):
        """发布识别结果"""
        msg = String()
        msg.data = text
        self.result_pub.publish(msg)
        self.get_logger().info(
            f'发布识别结果: "{text}" (置信度: {confidence:.2f})')

    def _publish_status(self, status: str):
        """发布 ASR 状态"""
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    # ================================================================
    #  唤醒词对话状态机
    # ================================================================
    def _set_state(self, new_state: str, publish: bool = True):
        """切换对话状态，发布 asr_status 并输出清晰日志"""
        old_state = self._state
        self._state = new_state
        if new_state == STATE_ACTIVE:
            # 进入对话模式，重置超时计时
            self._last_active_time = time.monotonic()
        if publish:
            self._publish_status(new_state)
        if old_state != new_state:
            self.get_logger().info(f'[状态切换] {old_state} → {new_state}')

    def _process_utterance(self, text: str):
        """根据当前状态处理一句识别结果"""
        text = (text or '').strip()
        if not text:
            return

        if self._state == STATE_IDLE:
            # 待机模式：只检查唤醒词，未命中则丢弃，不发布结果
            if self._match_wake_word(text):
                self.get_logger().info(
                    f'[待机] 命中唤醒词: "{text}" → 进入对话模式')
                # 唤醒提示音（880Hz x2）
                self._play_beep(freq=880, duration=0.15, repeat=2)
                self._set_state(STATE_ACTIVE, publish=True)
            else:
                self.get_logger().debug(f'[待机] 忽略非唤醒语音: "{text}"')
        elif self._state == STATE_ACTIVE:
            # 对话模式：有语音即刷新超时计时
            self._last_active_time = time.monotonic()
            if self._match_exit_command(text):
                self.get_logger().info(
                    f'[对话] 命中退出命令: "{text}" → 返回待机')
                # 退出提示音（440Hz）
                self._play_beep(freq=440, duration=0.2)
                self._set_state(STATE_IDLE, publish=True)
            else:
                self.get_logger().info(f'[对话] 识别结果: "{text}"')
                # 识别中提示音（660Hz x2）
                self._play_beep(freq=660, duration=0.1, repeat=2)
                self._publish_result(text)

    # ================================================================
    #  唤醒词 / 退出命令匹配
    # ================================================================
    @staticmethod
    def _normalize(text: str) -> str:
        """去除空白与常见标点，便于稳健匹配"""
        return re.sub(r'[\s，。！？、,.!?~～·…]', '', text or '')

    def _match_wake_word(self, text: str) -> bool:
        """检测文本是否包含唤醒词（支持字符级 + 拼音级模糊匹配）"""
        norm = self._normalize(text)
        if not norm:
            return False
        for ww in self._wake_words:
            target = self._normalize(ww)
            if not target:
                continue
            # 1) 完全包含
            if target in norm:
                return True
            # 2) 字符级模糊（编辑距离/字符重叠率，容忍漏字）
            if self._wake_word_fuzzy and self._fuzzy_contains(norm, target):
                return True
            # 3) 拼音级模糊（容忍同音错字，需 pypinyin）
            if self._wake_word_fuzzy and self._lazy_pinyin is not None:
                py_text = self._pinyin_str(norm)
                py_target = self._pinyin_str(target)
                if py_target and (py_target in py_text
                                  or self._fuzzy_contains(py_text, py_target)):
                    return True
        return False

    def _pinyin_str(self, text: str) -> str:
        """将中文转为拼接拼音串（无声调），失败时返回空串"""
        if self._lazy_pinyin is None:
            return ''
        try:
            return ''.join(self._lazy_pinyin(text))
        except Exception:
            return ''

    def _match_exit_command(self, text: str) -> bool:
        """检测文本是否包含退出命令"""
        norm = self._normalize(text)
        if not norm:
            return False
        for cmd in self._exit_commands:
            target = self._normalize(cmd)
            if target and target in norm:
                return True
        return False

    def _fuzzy_contains(self, text: str, target: str,
                        threshold: float = 0.6) -> bool:
        """模糊匹配：容忍 ASR 错字。

        策略：
          1) 滑动窗口相似度 —— 在 text 中寻找与 target 长度相近的片段，
             用 difflib 计算相似度，任一窗口 >= threshold 即命中
             （如 "小机人" vs "小机器人" 相似度约 0.86）。
          2) 关键字符重叠率 —— target 的去重字符在 text 中出现的比例
             >= threshold 也视为命中（应对插入/语序轻微变化）。
        """
        n = len(target)
        if n == 0 or not text:
            return False

        # 1) 滑动窗口相似度
        best = 0.0
        tlen = len(text)
        for win in (n - 1, n, n + 1):
            if win <= 0 or win > tlen:
                continue
            for i in range(0, tlen - win + 1):
                window = text[i:i + win]
                ratio = difflib.SequenceMatcher(None, window, target).ratio()
                if ratio > best:
                    best = ratio
                if best >= threshold:
                    return True

        # 2) 关键字符重叠率
        target_chars = set(target)
        common = sum(1 for ch in target_chars if ch in text)
        overlap = common / len(target_chars) if target_chars else 0.0
        return overlap >= threshold

    # ================================================================
    #  TTS 状态回调（TTS 播放时暂停录音）
    # ================================================================
    def tts_status_callback(self, msg: String):
        """处理 TTS 播放状态：speaking→暂停录音；idle→恢复录音

        仅设置标志位（跨线程 bool 赋值在 GIL 下是原子的），
        识别流重置与缓冲排空均在录音循环线程内完成，避免两线程
        同时读取同一 parec 管道引发竞争。
        """
        status = (msg.data or '').strip().lower()
        if status == 'speaking':
            if not self._tts_playing:
                self._tts_playing = True
                self.get_logger().info('[TTS] 开始播放 → 暂停录音（避免回声反馈）')
        elif status in ('idle', 'ready', 'done', 'finished', 'complete'):
            if self._tts_playing:
                self._tts_playing = False
                self.get_logger().info('[TTS] 播放结束 → 恢复录音')

    # ================================================================
    #  资源清理
    # ================================================================
    def destroy_node(self):
        """清理资源"""
        self._running = False
        if self._arecord_proc is not None:
            try:
                self._arecord_proc.terminate()
                self._arecord_proc.wait(timeout=3)
            except Exception:
                try:
                    self._arecord_proc.kill()
                except Exception:
                    pass
        self.get_logger().info('ASR 节点资源已释放')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ASRNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('ASR 节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
