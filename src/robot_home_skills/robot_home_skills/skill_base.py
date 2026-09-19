"""
技能基类
robot_home_skills/robot_home_skills/skill_base.py

定义所有家务技能的统一接口，包括:
- execute(): 执行技能
- cancel(): 取消执行
- get_status(): 获取当前状态
- reset(): 重置技能
"""

from enum import Enum
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class SkillStatus(Enum):
    """技能执行状态"""
    IDLE = 'idle'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILURE = 'failure'
    CANCELLED = 'cancelled'
    PAUSED = 'paused'


class SkillBase(ABC):
    """技能基类 - 所有家务技能必须继承此类"""

    def __init__(self, name: str, description: str = ''):
        """
        初始化技能

        Args:
            name: 技能名称标识符
            description: 技能描述
        """
        self._name = name
        self._description = description
        self._status = SkillStatus.IDLE
        self._progress = 0.0
        self._current_step = ''
        self._error_message = ''
        self._params: Dict[str, Any] = {}
        self._cancelled = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def current_step(self) -> str:
        return self._current_step

    @property
    def error_message(self) -> str:
        return self._error_message

    def get_status(self) -> Dict[str, Any]:
        """获取技能当前状态信息"""
        return {
            'name': self._name,
            'status': self._status.value,
            'progress': self._progress,
            'current_step': self._current_step,
            'error_message': self._error_message,
        }

    def execute(self, params: Optional[Dict[str, Any]] = None) -> SkillStatus:
        """
        执行技能

        Args:
            params: 执行参数字典

        Returns:
            SkillStatus: 执行结果状态
        """
        self._status = SkillStatus.RUNNING
        self._progress = 0.0
        self._current_step = 'starting'
        self._error_message = ''
        self._cancelled = False
        self._params = params or {}

        try:
            result = self._do_execute()
            if self._cancelled:
                self._status = SkillStatus.CANCELLED
            else:
                self._status = result
        except Exception as e:
            self._error_message = str(e)
            self._status = SkillStatus.FAILURE

        if self._status == SkillStatus.SUCCESS:
            self._progress = 1.0

        return self._status

    def cancel(self):
        """取消技能执行"""
        self._cancelled = True
        self._status = SkillStatus.CANCELLED
        self._on_cancel()

    def reset(self):
        """重置技能到初始状态"""
        self._status = SkillStatus.IDLE
        self._progress = 0.0
        self._current_step = ''
        self._error_message = ''
        self._cancelled = False
        self._params = {}

    def _update_progress(self, progress: float, step: str = ''):
        """更新进度和当前步骤"""
        self._progress = max(0.0, min(1.0, progress))
        if step:
            self._current_step = step

    @abstractmethod
    def _do_execute(self) -> SkillStatus:
        """
        实际执行逻辑 (子类必须实现)

        Returns:
            SkillStatus: 执行结果
        """
        raise NotImplementedError

    def _on_cancel(self):
        """取消时的清理操作 (子类可覆写)"""
        pass

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}('
            f'name="{self._name}", '
            f'status={self._status.value}, '
            f'progress={self._progress:.0%})'
        )
