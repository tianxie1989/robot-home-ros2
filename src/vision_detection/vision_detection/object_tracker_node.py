"""目标跟踪节点 - 持续追踪多个物体"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import math


class ObjectTrackerNode(Node):
    """简单的目标跟踪器，基于位置距离关联"""

    def __init__(self):
        super().__init__('object_tracker')

        self.declare_parameter('max_distance', 0.3)   # 最大关联距离(米)
        self.declare_parameter('max_lost_frames', 10)  # 最大丢失帧数

        self.max_distance = self.get_parameter('max_distance').value
        self.max_lost_frames = self.get_parameter('max_lost_frames').value

        # 订阅检测结果
        self.detection_sub = self.create_subscription(
            String, '/detected_objects', self.detection_callback, 10
        )

        # 发布跟踪结果
        self.track_pub = self.create_publisher(String, '/tracked_objects', 10)

        # 跟踪状态
        self.tracks = {}  # track_id -> {class_name, position, lost_count}
        self.next_track_id = 0

        self.get_logger().info('目标跟踪节点启动完成')

    def detection_callback(self, msg):
        """处理检测结果，更新跟踪"""
        data = json.loads(msg.data)
        detections = data.get('objects', [])

        # 简单最近邻关联
        matched_tracks = set()
        new_tracks = []

        for det in detections:
            best_track_id = None
            best_dist = float('inf')

            for track_id, track in self.tracks.items():
                if track_id in matched_tracks:
                    continue
                dist = self._bbox_distance(det, track)
                if dist < self.max_distance and dist < best_dist:
                    best_dist = dist
                    best_track_id = track_id

            if best_track_id is not None:
                # 更新已有track
                self.tracks[best_track_id].update({
                    'class_name': det['class_name'],
                    'bbox_x': det['bbox_x'],
                    'bbox_y': det['bbox_y'],
                    'bbox_width': det['bbox_width'],
                    'bbox_height': det['bbox_height'],
                    'confidence': det['confidence'],
                    'lost_count': 0,
                })
                matched_tracks.add(best_track_id)
            else:
                new_tracks.append(det)

        # 未匹配的track增加丢失计数
        for track_id in list(self.tracks.keys()):
            if track_id not in matched_tracks:
                self.tracks[track_id]['lost_count'] += 1
                if self.tracks[track_id]['lost_count'] > self.max_lost_frames:
                    del self.tracks[track_id]

        # 创建新track
        for det in new_tracks:
            self.tracks[self.next_track_id] = {**det, 'lost_count': 0}
            self.next_track_id += 1

        # 发布跟踪结果
        result = String()
        result.data = json.dumps({
            'tracks': [
                {'track_id': tid, **track}
                for tid, track in self.tracks.items()
            ],
            'total_tracks': len(self.tracks),
        })
        self.track_pub.publish(result)

    def _bbox_distance(self, det1, det2):
        """计算两个边界框中心的归一化距离"""
        cx1 = det1.get('bbox_x', 0) + det1.get('bbox_width', 0) / 2
        cy1 = det1.get('bbox_y', 0) + det1.get('bbox_height', 0) / 2
        cx2 = det2.get('bbox_x', 0) + det2.get('bbox_width', 0) / 2
        cy2 = det2.get('bbox_y', 0) + det2.get('bbox_height', 0) / 2
        return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) / 640.0  # 归一化


def main(args=None):
    rclpy.init(args=args)
    node = ObjectTrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
