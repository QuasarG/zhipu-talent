import faulthandler

# 任何测试卡死 30 秒即转储全部线程栈并退出（临时排查用）
faulthandler.dump_traceback_later(30, exit=True)
