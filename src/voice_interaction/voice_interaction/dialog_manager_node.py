"""
对话管理节点
voice_interaction/voice_interaction/dialog_manager_node.py

订阅语音识别结果文本，先尝试正则匹配确定性命令（捡玩具、整理房间等），
匹配不到时调用本地/局域网 Ollama ``/api/chat`` 进行开放对话，
并把语音反馈发布给 TTS 节点。

多轮对话历史由本节点自行维护（``max_history`` 控制保留轮数）；
当 ASR 回到待机（idle，配合唤醒词模式）时自动清空上下文。

LLM 请求在后台工作线程（queue.Queue）中执行，避免阻塞 ROS2 执行器
（Ollama 一次对话通常需要数百毫秒到数秒）。
"""

import re
import json
import queue
import threading
import time
import urllib.request
import urllib.error
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from typing import Optional, Dict, Tuple, List


# ================================================================
#  命令模式匹配规则（确定性命令，优先匹配）
# ================================================================
COMMAND_PATTERNS = [
    # 捡玩具相关
    (r'(捡|收|收拾|整理).*(玩具|积木)', 'pick_toy', {}),
    # 整理房间相关
    (r'(整理|收拾|打扫).*(房间|客厅|卧室|厨房)', 'cleanup_area',
     lambda m: {'area': _extract_area(m.group(0))}),
    # 叠衣服相关
    (r'(叠|折|整理).*(衣服|衣物|T恤)', 'fold_clothes', {}),
    # 分类相关
    (r'(分类|归类|分拣).*(物品|东西)', 'sort_objects', {}),
    # 简单抓取
    (r'(抓|拿|捡|拾取)', 'pick_toy', {}),
]

# 区域名称映射
AREA_MAP = {
    '客厅': 'living_room',
    '房间': 'living_room',
    '卧室': 'bedroom',
    '厨房': 'kitchen',
    '书房': 'study_room',
    '阳台': 'balcony',
}

# 确认/取消关键词
CONFIRM_KEYWORDS = ['好的', '确认', '是的', '继续', '可以', '行']
CANCEL_KEYWORDS = ['取消', '停止', '不要', '算了', '放弃', '退出']


def _extract_area(text: str) -> str:
    """从文本中提取区域标识"""
    for cn_name, en_name in AREA_MAP.items():
        if cn_name in text:
            return en_name
    return 'living_room'


class DialogManagerNode(Node):
    """对话管理节点 - 正则命令匹配 + 本地 Ollama LLM 开放对话"""

    # TTS 播报前需要清理的 Markdown 残留（LLM 回复常带格式符号），按顺序应用
    TTS_CLEAN_RULES = (
        (r'```.*?```', ' '),                      # 代码块整体丢弃
        (r'`([^`]*)`', r'\1'),                    # 行内代码去反引号
        (r'!?\[([^\]]*)\]\([^)]*\)', r'\1'),      # Markdown 链接/图片只留文字
        (r'[*_#>~|]+', ' '),                      # 加粗、斜体、标题、引用等符号
        (r'\s+', ' '),                            # 折叠空白与换行
        # 去掉中文/全角标点两侧因删除符号而残留的空格（否则 TTS 会读出停顿）
        (r'(?<=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])'
         r'\s+'
         r'(?=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', ''),
    )

    def __init__(self):
        super().__init__('dialog_manager')

        # ==================== 参数声明 ====================
        # ---------- Ollama 配置 ----------
        self.declare_parameter('ollama_url', 'http://localhost:11434')
        self.declare_parameter('ollama_model', 'qwen2.5:0.5b')
        self.declare_parameter('ollama_timeout', 30.0)

        # ---------- 通用配置 ----------
        # 是否启用 LLM 开放对话（false 则只做正则确定性命令匹配）
        self.declare_parameter('enable_llm', True)
        self.declare_parameter('system_prompt',
            '你是一个家用机器人的语音助手。回复要简短口语化，适合语音播报，'
            '每次回复控制在2-3句话以内。')
        self.declare_parameter('max_tokens', 256)
        self.declare_parameter('temperature', 0.7)
        self.declare_parameter('max_history', 10)            # 保留的对话历史轮数
        self.declare_parameter('tts_max_chars', 150)         # 播报最大字数

        # ==================== 参数读取 ====================
        self._use_llm = bool(self.get_parameter('enable_llm').value)

        # --- Ollama ---
        self._ollama_url = str(
            self.get_parameter('ollama_url').value or 'http://localhost:11434').rstrip('/')
        self._ollama_model = str(self.get_parameter('ollama_model').value).strip()
        self._ollama_timeout = float(self.get_parameter('ollama_timeout').value)

        # --- 通用 ---
        self._system_prompt = self.get_parameter('system_prompt').value
        self._max_tokens = self.get_parameter('max_tokens').value
        self._temperature = self.get_parameter('temperature').value
        self._tts_max_chars = int(self.get_parameter('tts_max_chars').value)
        self._max_history = max(0, int(self.get_parameter('max_history').value))

        if not self.ollama_ready:
            self.get_logger().warn(
                'Ollama 配置不完整（ollama_url / ollama_model 为空），LLM 开放对话将不可用')

        # ==================== 对话状态 ====================
        self._awaiting_confirm = False
        self._pending_command: Optional[Tuple[str, Dict]] = None
        self._chat_history: List[Dict] = []    # 本地对话历史
        self._history_lock = threading.Lock()  # 对话历史线程锁

        # LLM 请求后台队列（单工作线程，串行处理，避免阻塞 ROS2 回调）
        self._llm_queue: 'queue.Queue[str]' = queue.Queue(maxsize=4)
        self._llm_worker = threading.Thread(
            target=self._llm_worker_loop, name='dialog_llm_worker', daemon=True)
        self._llm_worker.start()

        # ==================== ROS2 话题 ====================
        # 订阅语音识别结果
        self.asr_sub = self.create_subscription(
            String, '/voice/recognition_text', self.asr_callback, 10)

        # 订阅 ASR 状态：当 ASR 回到待机（idle）时清空对话上下文
        self.asr_status_sub = self.create_subscription(
            String, '/voice/asr_status', self.asr_status_callback, 10)

        # 发布解析后的命令（JSON 格式: {"skill": "...", "params": {...}}）
        self.command_pub = self.create_publisher(
            String, '/voice/parsed_command', 10)

        # 发布语音反馈（给 TTS）
        self.speak_pub = self.create_publisher(
            String, '/voice/speak_text', 10)

        # 订阅任务状态
        self.task_state_sub = self.create_subscription(
            String, '/task/current_state', self.task_state_callback, 10)
        self._task_state = 'idle'

        self.get_logger().info(
            f'对话管理节点已启动 | LLM={"开" if self._use_llm else "关"} '
            f'| Ollama {self._ollama_url} model={self._ollama_model}'
        )

    # ================================================================
    #  后端可用性
    # ================================================================
    @property
    def ollama_ready(self) -> bool:
        """Ollama 后端是否具备调用条件"""
        return bool(self._ollama_url) and bool(self._ollama_model)

    # ================================================================
    #  ROS2 回调
    # ================================================================
    def task_state_callback(self, msg: String):
        """更新任务状态"""
        self._task_state = msg.data

    def asr_status_callback(self, msg: String):
        """处理 ASR 状态：回到待机（idle）时清空对话历史与上下文"""
        status = (msg.data or '').strip().lower()
        if status == 'idle':
            self._reset_dialog_context()

    def _reset_dialog_context(self):
        """清空一轮对话的全部上下文（本地历史、待确认命令）"""
        with self._history_lock:
            had_history = bool(self._chat_history)
            self._chat_history.clear()
        self._awaiting_confirm = False
        self._pending_command = None
        if had_history:
            self.get_logger().info('ASR 进入待机 → 已清空对话历史与上下文')

    def asr_callback(self, msg: String):
        """处理语音识别文本"""
        text = msg.data.strip()
        if not text:
            return

        self.get_logger().info(f'语音输入: "{text}"')

        # 如果正在等待确认
        if self._awaiting_confirm:
            self._handle_confirm_response(text)
            return

        # 检查是否为取消命令
        for keyword in CANCEL_KEYWORDS:
            if keyword in text:
                self._handle_cancel()
                return

        # 尝试匹配确定性命令模式
        command = self._parse_command(text)

        if command is not None:
            skill_name, params = command
            self.get_logger().info(f'识别命令: {skill_name}, 参数: {params}')

            # 请求确认
            self._pending_command = command
            self._awaiting_confirm = True
            self._speak(f'你是要我执行{skill_name}吗？请说"好的"确认或"取消"放弃')
        else:
            # 正则匹配不到 → 交给 Ollama 处理开放对话
            if self._use_llm:
                self._submit_llm_chat(text)
            else:
                self.get_logger().info(f'无法识别的语音指令: "{text}"')
                self._speak('抱歉，我没有听懂。你可以说"捡玩具"、"整理客厅"或"叠衣服"')

    # ================================================================
    #  LLM 后台工作线程（Ollama 一次对话数百 ms~数 s，不能阻塞 ROS2 执行器）
    # ================================================================
    def _submit_llm_chat(self, user_text: str):
        """把开放对话请求投递到后台队列，立即返回"""
        try:
            self._llm_queue.put_nowait(user_text)
        except queue.Full:
            self.get_logger().warn(
                'LLM 请求队列已满，丢弃本次输入（上一条对话仍在处理中）')

    def _llm_worker_loop(self):
        """后台单工作线程：串行消费 LLM 请求"""
        while rclpy.ok():
            try:
                user_text = self._llm_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_llm_chat(user_text)
            except Exception as e:   # 工作线程必须兜底，否则线程静默死亡
                self.get_logger().error(f'LLM 工作线程异常: {e}')
                try:
                    self._speak('抱歉，我出了点问题，请稍后再试')
                except Exception:    # noqa: BLE001 节点已销毁时忽略
                    return
            finally:
                self._llm_queue.task_done()

    # ================================================================
    #  Ollama 对话
    # ================================================================
    def _handle_llm_chat(self, user_text: str):
        """调用 Ollama 完成一轮开放对话：调用 → 记录历史 → 播报"""
        self.get_logger().info(f'[LLM 请求] "{user_text}"')

        if not self.ollama_ready:
            self.get_logger().error('Ollama 后端不可用（ollama_url / ollama_model 未配置）')
            self._speak('抱歉，我的大脑没有连接上，请稍后再试')
            return

        reply, err = self._try_ollama(user_text)
        if not reply:
            self.get_logger().error(
                f'Ollama 调用失败: {err}（请确认 {self._ollama_url} 服务已启动）')
            self._speak('抱歉，我的大脑没有连接上，请稍后再试')
            return

        with self._history_lock:
            self._chat_history.append({'role': 'user', 'content': user_text})
            self._chat_history.append({'role': 'assistant', 'content': reply})
            max_entries = self._max_history * 2
            if max_entries > 0 and len(self._chat_history) > max_entries:
                self._chat_history = self._chat_history[-max_entries:]

        self.get_logger().info(f'[LLM 回复] "{reply}"')
        self._speak(self._sanitize_for_tts(reply))

    def _try_ollama(self, user_text: str) -> Tuple[str, str]:
        """调用 Ollama，返回 (回复文本, 错误描述)；成功时错误描述为空串"""
        started = time.monotonic()
        try:
            reply = self._call_ollama(user_text)
        except urllib.error.HTTPError as e:
            return '', f'HTTP {e.code}: {self._read_http_error(e)}'
        except urllib.error.URLError as e:
            return '', f'网络连接失败: {e.reason}'
        except Exception as e:   # noqa: BLE001
            return '', f'未预期异常: {type(e).__name__}: {e}'

        elapsed_ms = (time.monotonic() - started) * 1000.0
        if not reply:
            return '', f'Ollama 返回内容为空（耗时 {elapsed_ms:.0f} ms）'
        self.get_logger().info(
            f'[Ollama] 对话成功，模型={self._ollama_model}，耗时 {elapsed_ms:.0f} ms')
        return reply, ''

    def _call_ollama(self, user_text: str) -> str:
        """
        调用 Ollama HTTP API 进行对话
        使用 urllib.request 避免额外依赖
        """
        # 构造消息列表（Ollama 无服务端会话，历史由本节点携带）
        messages = [{'role': 'system', 'content': self._system_prompt}]
        with self._history_lock:
            messages.extend(self._chat_history)
        messages.append({'role': 'user', 'content': user_text})

        payload = json.dumps({
            'model': self._ollama_model,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': self._temperature,
                'num_predict': self._max_tokens,
            }
        }, ensure_ascii=False).encode('utf-8')

        url = f'{self._ollama_url}/api/chat'
        req = urllib.request.Request(
            url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=self._ollama_timeout) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return str((result.get('message') or {}).get('content') or '').strip()

    # ================================================================
    #  TTS 文本净化
    # ================================================================
    def _sanitize_for_tts(self, text: str) -> str:
        """清理 Markdown 符号并按最大字数截断，避免 TTS 念出格式字符"""
        cleaned = (text or '').strip()
        for pattern, repl in self.TTS_CLEAN_RULES:
            cleaned = re.sub(pattern, repl, cleaned, flags=re.S)
        cleaned = cleaned.strip(' -:：')

        limit = self._tts_max_chars
        if limit > 0 and len(cleaned) > limit:
            cut = cleaned[:limit]
            # 尽量在标点处收尾，避免语音被硬生生切断
            for sep in ('。', '！', '？', '，', '、', '；', ' '):
                idx = cut.rfind(sep)
                if idx >= limit * 0.5:
                    cut = cut[:idx + 1]
                    break
            cleaned = cut.strip()
            if cleaned and cleaned[-1] not in '。！？':
                cleaned += '。'
            self.get_logger().info(
                f'回复超过 {limit} 字，已截断为 {len(cleaned)} 字后播报')

        return cleaned or (text or '').strip()

    @staticmethod
    def _read_http_error(err: 'urllib.error.HTTPError') -> str:
        """尽量从 HTTP 错误体里提取 Ollama 的业务错误信息"""
        try:
            body = err.read().decode('utf-8', errors='replace')
        except Exception:   # noqa: BLE001
            return str(getattr(err, 'reason', err))
        try:
            obj = json.loads(body)
            return str(obj)[:300]
        except (ValueError, TypeError):
            return body[:300]

    # ================================================================
    #  命令解析
    # ================================================================
    def _parse_command(self, text: str) -> Optional[Tuple[str, Dict]]:
        """解析文本为命令"""
        for pattern, skill_name, params_factory in COMMAND_PATTERNS:
            match = re.search(pattern, text)
            if match:
                if callable(params_factory):
                    params = params_factory(match)
                else:
                    params = params_factory.copy()
                return (skill_name, params)
        return None

    # ================================================================
    #  确认/取消处理
    # ================================================================
    def _handle_confirm_response(self, text: str):
        """处理确认/取消响应"""
        self._awaiting_confirm = False

        # 检查确认
        for keyword in CONFIRM_KEYWORDS:
            if keyword in text:
                if self._pending_command:
                    skill_name, params = self._pending_command
                    self._send_command(skill_name, params)
                    self._speak(f'好的，开始执行{skill_name}')
                self._pending_command = None
                return

        # 检查取消
        for keyword in CANCEL_KEYWORDS:
            if keyword in text:
                self._pending_command = None
                self._speak('好的，已取消')
                return

        # 未识别的响应，取消当前操作
        self._pending_command = None
        self._speak('没有听清，已取消操作。请重新说一次')

    def _handle_cancel(self):
        """处理取消命令"""
        if self._pending_command:
            self._pending_command = None
            self._awaiting_confirm = False

        self._speak('好的，已取消')
        self.get_logger().info('用户取消了操作')

    # ================================================================
    #  发布方法
    # ================================================================
    def _send_command(self, skill_name: str, params: Dict):
        """发送解析后的命令"""
        msg = String()
        msg.data = json.dumps({
            'skill': skill_name,
            'params': params,
        })
        self.command_pub.publish(msg)

    def _speak(self, text: str):
        """发布语音反馈"""
        msg = String()
        msg.data = text
        self.speak_pub.publish(msg)
        self.get_logger().info(f'[对话反馈] {text}')


def main(args=None):
    rclpy.init(args=args)
    node = DialogManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('对话管理节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
