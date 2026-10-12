"""显存账本（model_residency）的单测：不碰显卡、不碰音频、不碰 Qt

账本本身是纯逻辑（登记、计时、该不该放），所以这里全部用假的释放回调来验：
每一"次"释放就是在计数器上加一。真正"放掉之后显存有没有下来"由
`check_gpu_reclaim.py` 那台真机器上的探针来量。

跑法：python test_model_residency.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model_residency import ModelResidency, free_cuda_cache


class _Counter:
    """假的"被管的模型"：调一次 release_fn 就记一笔"""

    def __init__(self, fail_times=0, on_release=None):
        self.calls = 0
        self.fail_times = fail_times
        self.on_release = on_release

    def __call__(self):
        self.calls += 1
        if self.on_release is not None:
            self.on_release()
        if self.calls <= self.fail_times:
            raise RuntimeError("模拟卸载失败")


class ResidencyTest(unittest.TestCase):
    def setUp(self):
        self.book = ModelResidency()

    # ------------------------------------------------------------ 基本记账

    def test_touch_marks_resident_and_resets_idle(self):
        """touch 之后才算「占着」，闲置计时从那一刻起算"""
        counter = _Counter()
        self.book.register("a", "甲", counter, idle_timeout=60)
        self.assertFalse(self.book.snapshot()[0]["resident"],
                         "刚登记（还没用过）不该当成占着显存")

        self.book.touch("a")
        self.assertTrue(self.book.snapshot()[0]["resident"])

        # 时间往前推：touch 过、但没到超时的，sweep 不动它
        self.assertEqual(self.book.sweep(now=time.time() + 10), 0,
                         "闲置 10 秒、超时 60 秒：不该放")
        self.assertEqual(counter.calls, 0)

        # 再 touch 一次，超时重新起算（"刚用过"就是刚用过）
        self.book.touch("a")
        self.assertEqual(self.book.sweep(now=time.time() + 59), 0)

    def test_touch_unknown_key_is_harmless(self):
        """没登记过的 key：touch 静默忽略（工作线程里可能先用了再登记）"""
        self.book.touch("不存在")
        self.assertEqual(self.book.snapshot(), [])

    def test_release_runs_once_and_marks_not_resident(self):
        counter = _Counter()
        self.book.register("a", "甲", counter)
        self.book.touch("a")

        self.assertTrue(self.book.release("a"))
        self.assertEqual(counter.calls, 1)
        self.assertFalse(self.book.snapshot()[0]["resident"])
        self.assertEqual(self.book.snapshot()[0]["release_count"], 1)

        # 已经不在驻留状态：再 release 是空操作（不会重复卸）
        self.assertFalse(self.book.release("a"))
        self.assertEqual(counter.calls, 1)

    def test_release_unknown_key_returns_false(self):
        self.assertFalse(self.book.release("没登记"))

    # ------------------------------------------------------------ 闲置回收

    def test_sweep_releases_only_after_timeout(self):
        """到点才放：早一秒不动，晚一秒放掉，且只放一次"""
        counter = _Counter()
        self.book.register("a", "甲", counter, idle_timeout=30)
        self.book.touch("a")
        start = time.time()

        self.assertEqual(self.book.sweep(now=start + 29), 0)
        self.assertEqual(counter.calls, 0)

        self.assertEqual(self.book.sweep(now=start + 30), 1)
        self.assertEqual(counter.calls, 1)

        # 再 sweep 不会重复调（账上已经不驻留了）
        self.assertEqual(self.book.sweep(now=start + 999), 0)
        self.assertEqual(counter.calls, 1)

    def test_zero_timeout_never_sweeps(self):
        """idle_timeout = 0 表示「不参与闲置自动卸载」（只认手动）"""
        counter = _Counter()
        self.book.register("a", "甲", counter, idle_timeout=0)
        self.book.touch("a")
        self.assertEqual(self.book.sweep(now=time.time() + 100000), 0)
        self.assertEqual(counter.calls, 0)

    def test_touch_does_not_restart_while_releasing(self):
        """释放过程中回调里顺手 touch 一下，不该把它又标成"占着"

        真实的坑：`_release_stream_engine` 里做的事（unload / empty_cache）如果哪天
        顺手 touch 了，这项就永远"驻留着"，sweep 再也放不掉它。
        """
        counter = _Counter(on_release=lambda: self.book.touch("a"))
        self.book.register("a", "甲", counter)
        self.book.touch("a")
        self.book.release("a")
        self.assertFalse(self.book.snapshot()[0]["resident"])

    # ------------------------------------------------------------ guard

    def test_guard_blocks_unless_forced(self):
        """guard 说「正在用」就不许卸；force=True 才放行（停止/退出时的兜底）"""
        counter = _Counter()
        busy = {"value": True}
        self.book.register("a", "甲", counter, guard_fn=lambda: not busy["value"])
        self.book.touch("a")

        self.assertFalse(self.book.release("a"))
        self.assertEqual(counter.calls, 0)
        self.assertTrue(self.book.snapshot()[0]["resident"],
                        "被 guard 拦下时账目必须还是「占着」，否则再也没人管它")

        self.assertTrue(self.book.release("a", force=True))
        self.assertEqual(counter.calls, 1)
        self.assertFalse(self.book.snapshot()[0]["resident"])

    def test_guard_exception_lets_release_through(self):
        """guard 自己抛异常不许拦着回收（记一笔，然后照样放）"""
        counter = _Counter()

        def bad_guard():
            raise RuntimeError("guard 坏了")

        self.book.register("a", "甲", counter, guard_fn=bad_guard)
        self.book.touch("a")
        self.assertTrue(self.book.release("a"))
        self.assertEqual(counter.calls, 1)

    # ------------------------------------------------------------ 批量

    def test_release_others_keeps_the_named_ones(self):
        counters = {key: _Counter() for key in ("asr_simul", "asr_batch", "llm")}
        for key, counter in counters.items():
            self.book.register(key, key, counter)
            self.book.touch(key)

        self.assertEqual(self.book.release_others(keep={"asr_simul", "llm"}), 1)
        self.assertEqual(counters["asr_batch"].calls, 1)
        self.assertEqual(counters["asr_simul"].calls, 0)
        self.assertEqual(counters["llm"].calls, 0)

    def test_release_all_reports_released_and_skipped(self):
        """release_all 返回 (放下几项, 几项没放下)——界面要报给用户看"""
        blocked = _Counter()
        free = _Counter()
        self.book.register("busy", "忙", blocked, guard_fn=lambda: False)
        self.book.register("idle", "闲", free)
        self.book.touch("busy")
        self.book.touch("idle")

        self.assertEqual(self.book.release_all(), (1, 1))
        self.assertEqual(free.calls, 1)
        self.assertEqual(blocked.calls, 0)

        # force 之后连被 guard 拦的也放掉
        self.assertEqual(self.book.release_all(force=True), (1, 0))
        self.assertEqual(blocked.calls, 1)

    def test_release_all_on_empty_book(self):
        self.assertEqual(self.book.release_all(), (0, 0))

    # ------------------------------------------------------------ 失败与状态

    def test_release_fn_error_keeps_it_resident(self):
        """卸失败了：账上必须还是"占着"，否则它就再也不会被回收

        这一轮要修的正是这种静默的漏——"以为放掉了，其实还挂在那儿"。
        """
        counter = _Counter(fail_times=1)
        self.book.register("a", "甲", counter)
        self.book.touch("a")

        self.assertFalse(self.book.release("a"))
        entry = self.book.snapshot()[0]
        self.assertTrue(entry["resident"])
        self.assertIn("RuntimeError", entry["last_release_error"])

        # 下一次再试就成功了，错误也清掉
        self.assertTrue(self.book.release("a"))
        self.assertEqual(counter.calls, 2)
        self.assertFalse(self.book.snapshot()[0]["resident"])
        self.assertIsNone(self.book.snapshot()[0]["last_release_error"])

    def test_mark_released_does_not_call_release_fn(self):
        """模型被上游自己卸掉了：只改账目，别再发一次卸载请求"""
        counter = _Counter()
        self.book.register("a", "甲", counter)
        self.book.touch("a")
        self.book.mark_released("a")
        self.assertFalse(self.book.snapshot()[0]["resident"])
        self.assertEqual(counter.calls, 0)

    def test_set_idle_timeout(self):
        counter = _Counter()
        self.book.register("a", "甲", counter, idle_timeout=300)
        self.book.set_idle_timeout("a", 0)
        self.assertEqual(self.book.snapshot()[0]["idle_timeout"], 0)
        # 没登记过的 key 不会凭空冒出来
        self.book.set_idle_timeout("没有这个", 60)
        self.assertEqual(len(self.book.snapshot()), 1)

    def test_unregister_drops_the_entry(self):
        self.book.register("a", "甲", _Counter())
        self.book.unregister("a")
        self.assertEqual(self.book.snapshot(), [])

    def test_describe_mentions_every_entry(self):
        self.book.register("asr_simul", "流式识别", _Counter())
        self.book.register("llm", "本地翻译", _Counter())
        self.book.touch("llm")
        text = self.book.describe()
        self.assertIn("流式识别", text)
        self.assertIn("本地翻译", text)
        self.assertIn("已卸载", text)
        self.assertIn("驻留", text)


class FreeCudaCacheTest(unittest.TestCase):
    def test_free_cuda_cache_never_raises(self):
        """没有显卡/没有 torch 也必须安静的返回（它会被当收尾动作到处调用）"""
        self.assertIsInstance(free_cuda_cache(), bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
