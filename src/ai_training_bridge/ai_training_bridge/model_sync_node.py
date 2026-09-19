"""
模型同步节点
ai_training_bridge/ai_training_bridge/model_sync_node.py

通过 MQTT 订阅模型更新通知，当训练服务器发布新模型时，
使用 HTTP 下载模型文件并保存到本地模型目录。
"""

import os
import json
import threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ModelSyncNode(Node):
    """模型同步节点 - MQTT 订阅 + HTTP 下载"""

    def __init__(self):
        super().__init__('model_sync')

        # 参数声明
        self.declare_parameter('mqtt_broker_host', 'localhost')
        self.declare_parameter('mqtt_broker_port', 1883)
        self.declare_parameter('mqtt_topic', 'robot_home/model/update')
        self.declare_parameter('model_base_url', 'http://localhost:8080/models')
        self.declare_parameter('model_save_dir', '/tmp/robot_home/models')
        self.declare_parameter('auto_download', True)

        self._broker_host = self.get_parameter('mqtt_broker_host').value
        self._broker_port = self.get_parameter('mqtt_broker_port').value
        self._mqtt_topic = self.get_parameter('mqtt_topic').value
        self._model_base_url = self.get_parameter('model_base_url').value
        self._model_save_dir = self.get_parameter('model_save_dir').value
        self._auto_download = self.get_parameter('auto_download').value

        # 确保模型目录存在
        os.makedirs(self._model_save_dir, exist_ok=True)

        # MQTT 客户端
        self._mqtt_client = None
        self._init_mqtt()

        # 发布模型状态
        self.model_status_pub = self.create_publisher(
            String,
            '/ai/model_status',
            10
        )

        # 发布下载进度
        self.download_progress_pub = self.create_publisher(
            String,
            '/ai/download_progress',
            10
        )

        # 订阅手动触发下载
        self.download_cmd_sub = self.create_subscription(
            String,
            '/ai/download_model_cmd',
            self.download_cmd_callback,
            10
        )

        # 当前模型版本
        self._current_version = ''
        self._downloading = False

        self.get_logger().info(
            f'模型同步节点已启动 (MQTT: {self._broker_host}:{self._broker_port}, '
            f'模型目录: {self._model_save_dir})'
        )

    def _init_mqtt(self):
        """初始化 MQTT 客户端"""
        try:
            import paho.mqtt.client as mqtt

            self._mqtt_client = mqtt.Client(
                client_id='robot_home_model_sync',
                protocol=mqtt.MQTTv311,
            )

            self._mqtt_client.on_connect = self._on_mqtt_connect
            self._mqtt_client.on_message = self._on_mqtt_message
            self._mqtt_client.on_disconnect = self._on_mqtt_disconnect

            # 非阻塞连接
            self._mqtt_client.connect_async(
                self._broker_host,
                self._broker_port,
                keepalive=60,
            )
            self._mqtt_client.loop_start()

            self.get_logger().info(
                f'MQTT 连接请求已发送: {self._broker_host}:{self._broker_port}'
            )
        except ImportError:
            self.get_logger().warn(
                'paho-mqtt 未安装，MQTT 功能不可用。'
                '可通过 /ai/download_model_cmd 话题手动触发下载。'
            )
        except Exception as e:
            self.get_logger().error(f'MQTT 初始化失败: {e}')

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT 连接回调"""
        if rc == 0:
            self.get_logger().info('MQTT 连接成功')
            client.subscribe(self._mqtt_topic)
            self.get_logger().info(f'已订阅主题: {self._mqtt_topic}')
        else:
            self.get_logger().error(f'MQTT 连接失败, 返回码: {rc}')

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT 断开连接回调"""
        self.get_logger().warn(f'MQTT 断开连接, 返回码: {rc}')

    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT 消息回调 - 收到模型更新通知"""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            self.get_logger().info(f'收到模型更新通知: {payload}')

            model_name = payload.get('model_name', 'unknown')
            version = payload.get('version', '0.0.0')
            download_url = payload.get('download_url', '')

            if not download_url:
                download_url = f'{self._model_base_url}/{model_name}/{version}/model.pt'

            if version != self._current_version:
                self.get_logger().info(
                    f'新模型版本: {model_name} v{version} (当前: {self._current_version})'
                )

                if self._auto_download:
                    self._download_model(model_name, version, download_url)
            else:
                self.get_logger().info(f'模型已是最新版本: v{version}')

        except json.JSONDecodeError:
            self.get_logger().error('MQTT 消息解析失败，非 JSON 格式')
        except Exception as e:
            self.get_logger().error(f'处理 MQTT 消息失败: {e}')

    def download_cmd_callback(self, msg: String):
        """处理手动下载命令"""
        try:
            cmd = json.loads(msg.data)
            model_name = cmd.get('model_name', 'unknown')
            version = cmd.get('version', 'latest')
            download_url = cmd.get('url', f'{self._model_base_url}/{model_name}/{version}/model.pt')

            self._download_model(model_name, version, download_url)
        except json.JSONDecodeError:
            self.get_logger().error('下载命令格式错误，需要 JSON 格式')

    def _download_model(self, model_name: str, version: str, url: str):
        """下载模型文件 (HTTP)"""
        if self._downloading:
            self.get_logger().warn('正在下载中，忽略重复请求')
            return

        # 在后台线程中执行下载
        thread = threading.Thread(
            target=self._do_download,
            args=(model_name, version, url),
            daemon=True,
        )
        thread.start()

    def _do_download(self, model_name: str, version: str, url: str):
        """执行实际下载操作"""
        self._downloading = True
        save_path = os.path.join(self._model_save_dir, model_name, version)
        os.makedirs(save_path, exist_ok=True)
        file_path = os.path.join(save_path, 'model.pt')

        self.get_logger().info(f'开始下载模型: {url} -> {file_path}')
        self._publish_status('downloading', model_name, version)

        try:
            import urllib.request
            urllib.request.urlretrieve(url, file_path)

            self._current_version = version
            self.get_logger().info(f'模型下载成功: {file_path}')
            self._publish_status('completed', model_name, version)

        except Exception as e:
            self.get_logger().error(f'模型下载失败: {e}')
            self._publish_status('failed', model_name, version, str(e))
        finally:
            self._downloading = False

    def _publish_status(self, status: str, model_name: str = '', version: str = '', error: str = ''):
        """发布模型状态"""
        msg = String()
        msg.data = json.dumps({
            'status': status,
            'model_name': model_name,
            'version': version,
            'error': error,
        })
        self.model_status_pub.publish(msg)

    def destroy_node(self):
        """清理 MQTT 资源"""
        if self._mqtt_client is not None:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ModelSyncNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('模型同步节点被用户中断')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
