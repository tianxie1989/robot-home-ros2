# 语音识别结果消息
# voice_interfaces/msg/SpeechRecognitionResult.msg

# 识别出的文本
string text

# 识别置信度 (0.0 ~ 1.0)
float32 confidence

# 识别时间戳
builtin_interfaces/Time timestamp

# 是否为最终结果 (true=最终结果, false=中间结果)
bool is_final

# 说话人标识 (如支持说话人识别)
string speaker_id

# 语言代码 (如: zh-CN, en-US)
string language
