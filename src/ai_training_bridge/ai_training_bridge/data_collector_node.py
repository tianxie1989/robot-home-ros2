"""
数据采集节点
ai_training_bridge/ai_training_bridge/data_collector_node.py

收集用户反馈和难例样本，用于模型持续改进。
订阅视觉检测结果和任务执行结果，保存难例数据到本地文件，
可定期上传到训练服务器。
"""

import os
import json
import time
from datetime import datetime
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DataCollectorNode(Node):
    """数据采集节点 - 收集用户反馈和难例样本"""

    def __init__(self):
        super().__init__('data_collector')

        # 参数声明
        self.declare_parameter('data_save_dir', '/tmp/robot_home/collected_data')
        self.declare_parameter('max_samples_per_file', 100)
        self.declare_parameter('upload_enabled', False)
        self.declare_parameter('upload_url', 'http://localhost:8080/api/upload')

        self._data_save_dir = self.get_parameter('data_save_dir').value
        self._max_samples = self.get_parameter('max_samples_per_file').value
        self._upload_enabled = self.get_parameter('upload_enabled').value
        self._upload_url = self.get_parameter('upload_url').value

        # 确保数据目录存在
        os.makedirs(self._data_save_dir, exist_ok=True)

        # 样本缓存
        self._samples = []
        self._sample_count = 0
        self._file_index = 0

        # 订阅检测结果 (难例收集)
        self.detection_sub = self.create_subscription(
            String,
            '/vision/detection_result_json',
            self.detection_callback,
            10
        )

        # 订阅用户反馈
        self.feedback_sub = self.create_subscription(
            String,
            '/ai/user_feedback',
            self.feedback_callback,
            10
        )

        # 订阅任务执行结果
        self.task_result_sub = self.create_subscription(
            String,
            '/task/current_state',
            self.task_state_callback,
            10
        )

        # 发布采集状态
        self.status_pub = self.create_publisher(
            String,
            '/ai/collector_status',
            10
        )

        # 定期保存定时器 (每30秒)
        self.save_timer = self.create_timer(30.0, self._save_samples)

        self.get_logger().info(
            f'数据采集节点已启动 (保存目录: {self._data_save_dir})'
        )

    def detection_callback(self, msg: String):
        """处理视觉检测结果 - 收集低置信度样本作为难例"""
        try:
            result = json.loads(msg.data)
            confidence = result.get('confidence', 1.0)

            # 低置信度检测结果视为难例
            if confidence < 0.5:
                sample = {
                    'type': 'hard_example',
                    'source': 'vision_detection',
                    'timestamp': datetime.now().isoformat(),
                    'data': result,
                    'confidence': confidence,
                }
                self._add_sample(sample)
                self.get_logger().debug(
                    f'收集难例样本: 置信度={confidence:.2f}'
                )
        except json.JSONDecodeError:
            pass

    def feedback_callback(self, msg: String):
        """处理用户反馈"""
        try:
            feedback = json.loads(msg.data)
            sample = {
                'type': 'user_feedback',
                'source': 'user',
                'timestamp': datetime.now().isoformat(),
                'data': feedback,
            }
            self._add_sample(sample)
            self.get_logger().info(f'收到用户反馈: {feedback.get("content", "")}')
        except json.JSONDecodeError:
            # 纯文本反馈
            sample = {
                'type': 'user_feedback',
                'source': 'user',
                'timestamp': datetime.now().isoformat(),
                'data': {'content': msg.data},
            }
            self._add_sample(sample)

    def task_state_callback(self, msg: String):
        """记录任务状态变化 (失败的任务作为难例)"""
        state = msg.data.strip()
        if state in ('failed', 'cancelled'):
            sample = {
                'type': 'task_failure',
                'source': 'task_planner',
                'timestamp': datetime.now().isoformat(),
                'data': {'state': state},
            }
            self._add_sample(sample)
            self.get_logger().info(f'收集任务失败样本: {state}')

    def _add_sample(self, sample: dict):
        """添加样本到缓存"""
        self._samples.append(sample)
        self._sample_count += 1

    def _save_samples(self):
        """保存样本到文件"""
        if not self._samples:
            return

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'samples_{timestamp}_{self._file_index}.json'
        filepath = os.path.join(self._data_save_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self._samples, f, ensure_ascii=False, indent=2)

            self.get_logger().info(
                f'已保存 {len(self._samples)} 个样本到: {filepath}'
            )

            self._samples.clear()
            self._file_index += 1

            # 发布状态
            status_msg = String()
            status_msg.data = json.dumps({
                'action': 'saved',
                'count': self._sample_count,
                'file': filepath,
            })
            self.status_pub.publish(status_msg)

        except Exception as e:
            self.get_logger().error(f'保存样本失败: {e}')

    def destroy_node(self):
        """退出前保存未写入的样本"""
        if self._samples:
            self._save_samples()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DataCollectorNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('数据采集节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
