"""
TTS 测试脚本
voice_interaction/test/test_tts.py

测试 TTS 节点的基本功能: 发送文本并验证响应
"""

import unittest
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TestTTSNode(unittest.TestCase):
    """TTS 节点测试"""

    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = Node('test_tts')
        self.received_status = []
        self.status_sub = self.node.create_subscription(
            String,
            '/voice/tts_status',
            self._status_callback,
            10
        )
        self.speak_pub = self.node.create_publisher(
            String,
            '/voice/speak_text',
            10
        )

    def tearDown(self):
        self.node.destroy_node()

    def _status_callback(self, msg: String):
        self.received_status.append(msg.data)

    def _spin_for(self, seconds: float):
        end_time = time.time() + seconds
        while time.time() < end_time:
            rclpy.spin_once(self.node, timeout_sec=0.1)

    def test_speak_message(self):
        """测试发送语音合成消息"""
        msg = String()
        msg.data = '测试语音输出'
        self.speak_pub.publish(msg)

        # 等待 TTS 节点处理
        self._spin_for(2.0)

        # 验证收到了状态消息
        self.assertTrue(
            len(self.received_status) > 0,
            '未收到 TTS 状态消息'
        )

    def test_empty_message(self):
        """测试空文本不应触发 TTS"""
        initial_count = len(self.received_status)
        msg = String()
        msg.data = '   '
        self.speak_pub.publish(msg)
        self._spin_for(1.0)

        self.assertEqual(
            len(self.received_status), initial_count,
            '空文本不应触发 TTS 状态变更'
        )


if __name__ == '__main__':
    unittest.main()
