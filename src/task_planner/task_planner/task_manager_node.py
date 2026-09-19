"""
任务管理主节点
task_planner/task_planner/task_manager_node.py

接收语音指令(文本形式)，解析为任务序列，通过行为树引擎调度技能执行。
订阅语音识别结果，发布任务状态。
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String
from enum import Enum
from typing import Dict, List, Optional

# 任务状态枚举
class TaskState(Enum):
    IDLE = 'idle'
    PARSING = 'parsing'
    PLANNING = 'planning'
    EXECUTING = 'executing'
    PAUSED = 'paused'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


# 任务类型映射
COMMAND_MAP = {
    '捡玩具': {'skill': 'pick_toy', 'params': {}},
    '收拾玩具': {'skill': 'pick_toy', 'params': {}},
    '整理房间': {'skill': 'cleanup_area', 'params': {'area': 'living_room'}},
    '收拾客厅': {'skill': 'cleanup_area', 'params': {'area': 'living_room'}},
    '叠衣服': {'skill': 'fold_clothes', 'params': {}},
    '分类物品': {'skill': 'sort_objects', 'params': {}},
    '抓取': {'skill': 'pick_toy', 'params': {}},
}


class TaskManagerNode(Node):
    """任务管理主节点 - 接收语音指令并调度技能执行"""

    def __init__(self):
        super().__init__('task_manager')

        # 当前任务状态
        self._state = TaskState.IDLE
        self._current_task: Optional[Dict] = None
        self._task_queue: List[Dict] = []
        self._task_counter = 0

        # 订阅语音识别结果(文本)
        self.voice_sub = self.create_subscription(
            String,
            '/voice/recognition_text',
            self.voice_callback,
            10
        )

        # 发布任务状态
        self.task_state_pub = self.create_publisher(
            String,
            '/task/current_state',
            10
        )

        # 发布语音反馈文本
        self.speech_pub = self.create_publisher(
            String,
            '/voice/speak_text',
            10
        )

        # 定时器: 任务执行循环
        self.execute_timer = self.create_timer(0.5, self.execute_loop)

        # 从行为树引擎导入
        from task_planner.behavior_tree_engine import BehaviorTreeEngine
        self.bt_engine = BehaviorTreeEngine(self)

        self.get_logger().info('任务管理节点已启动，等待语音指令...')
        self._publish_state()

    def voice_callback(self, msg: String):
        """处理语音识别结果"""
        text = msg.data.strip()
        if not text:
            return

        self.get_logger().info(f'收到语音指令: "{text}"')

        if self._state == TaskState.EXECUTING:
            self.get_logger().warn('当前正在执行任务，指令已入队')
            self._task_queue.append({'text': text})
            self._speak('收到，我会在完成当前任务后处理')
            return

        self._parse_and_execute(text)

    def _parse_and_execute(self, text: str):
        """解析语音文本并创建任务"""
        self._state = TaskState.PARSING
        self._publish_state()

        # 查找匹配的命令
        matched_skill = None
        matched_params = {}

        for keyword, cmd_info in COMMAND_MAP.items():
            if keyword in text:
                matched_skill = cmd_info['skill']
                matched_params = cmd_info['params'].copy()
                break

        if matched_skill is None:
            self.get_logger().warn(f'无法识别的指令: "{text}"')
            self._speak(f'抱歉，我没有理解"{text}"这个指令')
            self._state = TaskState.IDLE
            self._publish_state()
            return

        # 创建任务
        self._task_counter += 1
        task = {
            'id': self._task_counter,
            'name': matched_skill,
            'skill': matched_skill,
            'params': matched_params,
            'original_text': text,
        }

        self.get_logger().info(
            f'创建任务 #{task["id"]}: {task["skill"]} | 参数: {task["params"]}'
        )

        self._state = TaskState.PLANNING
        self._publish_state()

        # 使用行为树引擎规划执行
        success = self.bt_engine.build_tree(task)
        if success:
            self._current_task = task
            self._state = TaskState.EXECUTING
            self._publish_state()
            self._speak(f'好的，开始执行{task["skill"]}任务')
        else:
            self.get_logger().error(f'任务规划失败: {task}')
            self._state = TaskState.FAILED
            self._publish_state()
            self._speak('抱歉，任务规划失败，请稍后再试')
            self._state = TaskState.IDLE
            self._publish_state()

    def execute_loop(self):
        """任务执行主循环"""
        if self._state != TaskState.EXECUTING or self._current_task is None:
            return

        result = self.bt_engine.tick()

        if result == 'SUCCESS':
            self.get_logger().info(f'任务 #{self._current_task["id"]} 执行成功')
            self._speak(f'{self._current_task["skill"]}任务已完成')
            self._current_task = None
            self._state = TaskState.COMPLETED
            self._publish_state()
            self._process_queue()

        elif result == 'FAILURE':
            self.get_logger().error(f'任务 #{self._current_task["id"]} 执行失败')
            self._speak('抱歉，任务执行过程中遇到问题')
            self._current_task = None
            self._state = TaskState.FAILED
            self._publish_state()
            self._process_queue()

        elif result == 'RUNNING':
            pass  # 继续执行

    def _process_queue(self):
        """处理任务队列中的下一个任务"""
        if self._task_queue:
            next_task_text = self._task_queue.pop(0)['text']
            self.get_logger().info(f'从队列取出指令: "{next_task_text}"')
            self._parse_and_execute(next_task_text)
        else:
            self._state = TaskState.IDLE
            self._publish_state()

    def _speak(self, text: str):
        """发布语音合成文本"""
        msg = String()
        msg.data = text
        self.speech_pub.publish(msg)
        self.get_logger().info(f'[语音输出] {text}')

    def _publish_state(self):
        """发布当前任务状态"""
        msg = String()
        msg.data = self._state.value
        self.task_state_pub.publish(msg)

    def cancel_current_task(self):
        """取消当前执行的任务"""
        if self._current_task is not None:
            self.bt_engine.cancel()
            self._current_task = None
            self._state = TaskState.CANCELLED
            self._publish_state()
            self._speak('任务已取消')
            self._process_queue()


def main(args=None):
    rclpy.init(args=args)
    node = TaskManagerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('任务管理节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
