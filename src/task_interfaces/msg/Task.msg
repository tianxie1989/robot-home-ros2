# 任务定义消息
# task_interfaces/msg/Task.msg

# 任务唯一标识符
string id

# 任务名称 (如: pick_toy, cleanup_area, fold_clothes)
string name

# 任务状态 (idle, running, paused, completed, failed, cancelled)
uint8 STATUS_IDLE=0
uint8 STATUS_RUNNING=1
uint8 STATUS_PAUSED=2
uint8 STATUS_COMPLETED=3
uint8 STATUS_FAILED=4
uint8 STATUS_CANCELLED=5
uint8 status

# 任务参数 (JSON 格式字符串，如: {"area": "living_room"})
string params

# 任务创建时间戳
builtin_interfaces/Time created_at

# 任务完成时间戳
builtin_interfaces/Time completed_at

# 任务来源 (voice, api, schedule)
string source

# 优先级 (0=最低, 255=最高)
uint8 priority
