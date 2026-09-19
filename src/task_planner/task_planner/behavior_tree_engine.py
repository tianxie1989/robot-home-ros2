"""
简单行为树引擎
task_planner/task_planner/behavior_tree_engine.py

实现轻量级行为树框架，支持 Sequence / Selector / Action 节点类型。
用于将任务分解为有序的子步骤并驱动执行。
"""

import rclpy
from rclpy.node import Node
from enum import Enum
from typing import List, Callable, Optional


class BTStatus(Enum):
    """行为树节点状态"""
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
    RUNNING = 'RUNNING'
    IDLE = 'IDLE'


class BTNode:
    """行为树节点基类"""

    def __init__(self, name: str):
        self.name = name
        self._status = BTStatus.IDLE

    def tick(self) -> BTStatus:
        raise NotImplementedError

    def reset(self):
        self._status = BTStatus.IDLE

    @property
    def status(self) -> BTStatus:
        return self._status


class SequenceNode(BTNode):
    """顺序节点: 依次执行所有子节点，全部成功才成功"""

    def __init__(self, name: str, children: List[BTNode]):
        super().__init__(name)
        self.children = children
        self._current_index = 0

    def tick(self) -> BTStatus:
        while self._current_index < len(self.children):
            child = self.children[self._current_index]
            status = child.tick()

            if status == BTStatus.RUNNING:
                self._status = BTStatus.RUNNING
                return self._status
            elif status == BTStatus.FAILURE:
                self._status = BTStatus.FAILURE
                self._current_index = 0
                return self._status
            else:  # SUCCESS
                self._current_index += 1

        self._current_index = 0
        self._status = BTStatus.SUCCESS
        return self._status

    def reset(self):
        super().reset()
        self._current_index = 0
        for child in self.children:
            child.reset()


class SelectorNode(BTNode):
    """选择节点: 依次尝试子节点，任一成功即成功"""

    def __init__(self, name: str, children: List[BTNode]):
        super().__init__(name)
        self.children = children
        self._current_index = 0

    def tick(self) -> BTStatus:
        while self._current_index < len(self.children):
            child = self.children[self._current_index]
            status = child.tick()

            if status == BTStatus.RUNNING:
                self._status = BTStatus.RUNNING
                return self._status
            elif status == BTStatus.SUCCESS:
                self._current_index = 0
                self._status = BTStatus.SUCCESS
                return self._status
            else:  # FAILURE
                self._current_index += 1

        self._current_index = 0
        self._status = BTStatus.FAILURE
        return self._status

    def reset(self):
        super().reset()
        self._current_index = 0
        for child in self.children:
            child.reset()


class ActionNode(BTNode):
    """动作节点: 执行具体的技能动作"""

    def __init__(self, name: str, action_func: Callable, *args, **kwargs):
        super().__init__(name)
        self._action_func = action_func
        self._args = args
        self._kwargs = kwargs

    def tick(self) -> BTStatus:
        try:
            result = self._action_func(*self._args, **self._kwargs)
            if result is True or result == BTStatus.SUCCESS:
                self._status = BTStatus.SUCCESS
            elif result is False or result == BTStatus.FAILURE:
                self._status = BTStatus.FAILURE
            else:
                self._status = BTStatus.RUNNING
        except Exception as e:
            self._status = BTStatus.FAILURE
        return self._status


class BehaviorTreeEngine:
    """行为树引擎 - 构建和执行任务行为树"""

    def __init__(self, parent_node: Node):
        self._node = parent_node
        self._root: Optional[BTNode] = None
        self._cancelled = False
        self._logger = parent_node.get_logger()

    def build_tree(self, task: dict) -> bool:
        """根据任务字典构建行为树"""
        skill_name = task.get('skill', '')
        params = task.get('params', {})

        self._logger.info(f'为技能 "{skill_name}" 构建行为树')
        self._cancelled = False

        # 根据技能类型构建不同的行为树
        if skill_name == 'pick_toy':
            self._root = self._build_pick_toy_tree(params)
        elif skill_name == 'cleanup_area':
            area = params.get('area', 'living_room')
            self._root = self._build_cleanup_tree(area)
        elif skill_name == 'sort_objects':
            self._root = self._build_sort_objects_tree(params)
        elif skill_name == 'fold_clothes':
            self._root = self._build_fold_clothes_tree(params)
        else:
            self._logger.error(f'未知的技能类型: {skill_name}')
            return False

        return self._root is not None

    def tick(self) -> str:
        """执行一步行为树，返回 'SUCCESS' / 'FAILURE' / 'RUNNING'"""
        if self._root is None or self._cancelled:
            return 'FAILURE'

        status = self._root.tick()

        if status == BTStatus.SUCCESS:
            return 'SUCCESS'
        elif status == BTStatus.FAILURE:
            return 'FAILURE'
        else:
            return 'RUNNING'

    def cancel(self):
        """取消当前行为树执行"""
        self._cancelled = True
        if self._root:
            self._root.reset()
        self._logger.info('行为树执行已取消')

    # ---------- 技能行为树构建方法 ----------

    def _build_pick_toy_tree(self, params: dict) -> BTNode:
        """捡玩具技能行为树"""
        return SequenceNode('pick_toy_sequence', [
            ActionNode('detect_toys', self._action_detect_toys),
            ActionNode('navigate_to_toy', self._action_navigate_to_target),
            ActionNode('pick_object', self._action_pick),
            ActionNode('navigate_to_bin', self._action_navigate_to_bin),
            ActionNode('place_object', self._action_place),
        ])

    def _build_cleanup_tree(self, area: str) -> BTNode:
        """整理区域技能行为树"""
        return SequenceNode(f'cleanup_{area}_sequence', [
            ActionNode('scan_area', self._action_scan_area, area),
            ActionNode('detect_objects', self._action_detect_all_objects),
            SelectorNode('cleanup_loop', [
                SequenceNode('pick_and_store', [
                    ActionNode('pick_next', self._action_pick_next),
                    ActionNode('store_object', self._action_store),
                ]),
                ActionNode('cleanup_done', self._action_cleanup_done),
            ]),
        ])

    def _build_sort_objects_tree(self, params: dict) -> BTNode:
        """物品分类行为树"""
        return SequenceNode('sort_objects_sequence', [
            ActionNode('detect_all', self._action_detect_all_objects),
            ActionNode('classify_objects', self._action_classify),
            ActionNode('sort_and_place', self._action_sort_place),
        ])

    def _build_fold_clothes_tree(self, params: dict) -> BTNode:
        """叠衣服行为树"""
        return SequenceNode('fold_clothes_sequence', [
            ActionNode('detect_clothes', self._action_detect_clothes),
            ActionNode('pick_clothes', self._action_pick),
            ActionNode('fold_step', self._action_fold),
            ActionNode('place_folded', self._action_place),
        ])

    # ---------- 动作实现 (模拟/框架) ----------

    def _action_detect_toys(self) -> bool:
        self._logger.info('[BT] 检测玩具...')
        return True

    def _action_navigate_to_target(self) -> bool:
        self._logger.info('[BT] 导航到目标位置...')
        return True

    def _action_pick(self) -> bool:
        self._logger.info('[BT] 执行抓取...')
        return True

    def _action_navigate_to_bin(self) -> bool:
        self._logger.info('[BT] 导航到收纳箱...')
        return True

    def _action_place(self) -> bool:
        self._logger.info('[BT] 放置物体...')
        return True

    def _action_scan_area(self, area: str) -> bool:
        self._logger.info(f'[BT] 扫描区域: {area}')
        return True

    def _action_detect_all_objects(self) -> bool:
        self._logger.info('[BT] 检测所有物体...')
        return True

    def _action_pick_next(self) -> bool:
        self._logger.info('[BT] 抓取下一个物体...')
        return True

    def _action_store(self) -> bool:
        self._logger.info('[BT] 存储物体...')
        return True

    def _action_cleanup_done(self) -> bool:
        self._logger.info('[BT] 整理完成')
        return True

    def _action_classify(self) -> bool:
        self._logger.info('[BT] 分类物体...')
        return True

    def _action_sort_place(self) -> bool:
        self._logger.info('[BT] 分类放置...')
        return True

    def _action_detect_clothes(self) -> bool:
        self._logger.info('[BT] 检测衣物...')
        return True

    def _action_fold(self) -> bool:
        self._logger.info('[BT] 执行折叠动作...')
        return True


def main(args=None):
    """独立启动行为树引擎节点(用于调试)"""
    rclpy.init(args=args)
    node = Node('behavior_tree_engine')

    engine = BehaviorTreeEngine(node)

    # 演示: 构建并执行一个测试行为树
    test_task = {'skill': 'pick_toy', 'params': {}}
    if engine.build_tree(test_task):
        node.get_logger().info('测试行为树已构建，开始执行...')
        while rclpy.ok():
            result = engine.tick()
            if result != 'RUNNING':
                node.get_logger().info(f'行为树执行结果: {result}')
                break
            rclpy.spin_once(node, timeout_sec=0.1)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
