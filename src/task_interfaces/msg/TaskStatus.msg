# 任务状态消息
# task_interfaces/msg/TaskStatus.msg

# 关联的任务ID
string task_id

# 任务名称
string task_name

# 当前状态
uint8 STATUS_IDLE=0
uint8 STATUS_RUNNING=1
uint8 STATUS_PAUSED=2
uint8 STATUS_COMPLETED=3
uint8 STATUS_FAILED=4
uint8 STATUS_CANCELLED=5
uint8 status

# 进度百分比 (0.0 ~ 1.0)
float32 progress

# 当前子步骤描述
string current_step

# 错误信息 (状态为 FAILED 时)
string error_message

# 状态更新时间戳
builtin_interfaces/Time timestamp

# 已完成子步骤数
uint32 steps_completed

# 总子步骤数
uint32 steps_total
