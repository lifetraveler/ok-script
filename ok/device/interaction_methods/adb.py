import importlib
import time

from ok.device.capture_methods.base import BaseCaptureMethod
from ok.device.capture_methods.nemu_ipc import NemuIpcCaptureMethod
from ok.device.interaction_methods.base import BaseInteraction
from ok.device.interaction_methods.keys import ADB_KEY_MAP
from ok.device.interaction_methods.swipe import insert_swipe
from ok.util.logger import Logger

logger = Logger.get_logger(__name__)


class ADBInteraction(BaseInteraction):

    def __init__(self, device_manager, capture, device_width, device_height):
        super().__init__(capture)
        self.device_manager = device_manager
        self.device_width = device_width
        self.device_height = device_height
        self._u2 = None
        self._u2_device = None
        self.use_u2 = importlib.util.find_spec("uiautomator2")

    @property
    def width(self):
        return self.device_width

    @width.setter
    def width(self, value):
        self.device_width = value

    @property
    def height(self):
        return self.device_height

    @height.setter
    def height(self, value):
        self.device_height = value

    # ==================================================================
    # 按键 / 输入
    # ==================================================================
    def send_key(self, key, down_time=0.02):
        key = ADB_KEY_MAP.get(str(key).lower(), key)
        self.device_manager.device.shell(f"input keyevent {key}")

    def input_text(self, text):
        self.device_manager.shell(f"input text {text}")

    def back(self):
        self.send_key('KEYCODE_BACK')

    # ==================================================================
    # u2 懒加载
    # ==================================================================
    @property
    def u2(self):
        if self._u2 is None or self._u2_device != self.device_manager.device:
            logger.info(f'init u2 device')
            import uiautomator2
            self._u2_device = self.device_manager.device
            self._u2 = uiautomator2.connect(self._u2_device)
        return self._u2

    def _require_u2(self, method_name):
        if not self.use_u2:
            logger.warning(f"{method_name} requires uiautomator2, skipped")
            return False
        return True

    # ==================================================================
    # 滑动（原有实现，保持不变）
    # ==================================================================
    def swipe_nemu(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        p2 = (to_x, to_y)
        points = insert_swipe(p0=(from_x, from_y), p3=p2)

        for point in points:
            self.capture.nemu_impl.down(*point)
            time.sleep(0.010)

        start = time.time()
        while time.time() - start < settle_time:
            self.capture.nemu_impl.down(*p2)
            time.sleep(0.140)

        self.capture.nemu_impl.up()

        time.sleep(0.1)

    def swipe_u2(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        """
        Performs a swipe gesture using low-level touch events, allowing
        a pause ('settle_time') at the end point before lifting the touch.
        Note: The 'duration' parameter has limited effect on the actual
        movement speed when using basic touch.down/move/up events.
        The move itself is typically fast.
        Args:
            from_x (int): Starting X coordinate.
            from_y (int): Starting Y coordinate.
            to_x (int): Ending X coordinate.
            to_y (int): Ending Y coordinate.
            duration (float): Intended duration of the swipe (limited effect).
            settle_time (float): Seconds to pause at (to_x, to_y) before touch up.
        """
        # Touch down at the starting point
        self.u2.touch.down(from_x, from_y)
        # Optional small delay after touching down before starting move
        time.sleep(0.02)
        dx = to_x - from_x
        dy = to_y - from_y
        steps = int(max(abs(dx), abs(dy)) / 16)
        logger.debug(f'swipe steps: {steps}')
        for i in range(1, steps + 1):
            progress = i / steps
            current_x = int(from_x + dx * progress)
            current_y = int(from_y + dy * progress)
            self.u2.touch.move(current_x, current_y)
            # Sleep between steps (except potentially the last one before settle)
            if i < steps - 5:
                time.sleep(0.001)
            else:
                time.sleep(0.005)
        # Move to the ending point (move itself is usually quick)
        self.u2.touch.move(to_x, to_y)
        # Pause for settle_time seconds *before* lifting the finger
        if settle_time > 0:
            time.sleep(settle_time)
        # Lift the touch up at the ending point
        self.u2.touch.up(to_x, to_y)

    def swipe(self, from_x, from_y, to_x, to_y, duration, settle_time=0):
        if isinstance(self.capture, NemuIpcCaptureMethod):
            self.swipe_nemu(from_x, from_y, to_x, to_y, duration, settle_time)
        elif self.use_u2:
            self.swipe_u2(from_x, from_y, to_x, to_y, duration, settle_time)
        else:
            self.device_manager.device.shell(
                f"input swipe {round(from_x)} {round(from_y)} {round(to_x)} {round(to_y)} {duration}")

    # ==================================================================
    # 滚动 / 滚轮
    # ==================================================================
    def scroll_forward(self, percent=0.6, duration=0.3, settle_time=0):
        """
        向前滚动（内容向下移动，等同于手指从下往上滑）
        :param percent: 滑动幅度，占屏幕高度比例 0~1
        :param duration: 滑动时长
        :param settle_time: 松手前在终点停留时间
        """
        cx = self.device_width // 2
        start_y = int(self.device_height * 0.8)
        end_y = int(self.device_height * (0.8 - percent * 0.8))
        self.swipe(cx, start_y, cx, end_y, duration, settle_time)

    def scroll_backward(self, percent=0.6, duration=0.3, settle_time=0):
        """
        向后滚动（内容向上移动，等同于手指从上往下滑）
        """
        cx = self.device_width // 2
        start_y = int(self.device_height * 0.2)
        end_y = int(self.device_height * (0.2 + percent * 0.8))
        self.swipe(cx, start_y, cx, end_y, duration, settle_time)

    def scroll_page(self, direction="forward", percent=0.6, duration=0.3, settle_time=0):
        """
        统一页面滚动入口（内容滚动语义，区别于滚轮 scroll(x, y, count)）
        :param direction: "forward" / "backward" / "up" / "down"
        """
        if direction in ("forward", "up"):
            self.scroll_forward(percent, duration, settle_time)
        else:
            self.scroll_backward(percent, duration, settle_time)

    def fling(self, direction="forward", percent=0.8, duration=0.02):
        """
        快速滑动（带惯性），duration 越短越快，用于长列表快速浏览
        :param direction: forward / backward / up / down
        :param percent: 滑动幅度
        :param duration: 极短时长造成快速滑动
        """
        if direction in ("forward", "up"):
            self.scroll_forward(percent, duration)
        else:
            self.scroll_backward(percent, duration)

    def scroll_horizontal(self, direction="right", percent=0.6, duration=0.3):
        """
        水平滚动
        :param direction: "right"（内容向左移动，露出右侧）/ "left"
        """
        cy = self.device_height // 2
        if direction == "right":
            start_x = int(self.device_width * 0.8)
            end_x = int(self.device_width * (0.8 - percent * 0.8))
        else:
            start_x = int(self.device_width * 0.2)
            end_x = int(self.device_width * (0.2 + percent * 0.8))
        self.swipe(start_x, cy, end_x, cy, duration)

    # ==================================================================
    # 缩放（双指捏合 / 张开）
    # ==================================================================
    def _u2_root_object(self):
        """全屏 UiObject（空 selector）。
        u2 3.x 把 pinch_in/pinch_out 从 Device 挪到了 UiObject，server 端
        pinchIn/pinchOut RPC 仍在（真机验证可用）。"""
        return self.u2()

    def pinch_in(self, percent=50, steps=20):
        """
        双指捏合（缩小）
        :param percent: 缩放幅度 1~100，越大缩放范围越大
        :param steps: 步数，越大越平滑（速度越慢）
        """
        if not self._require_u2("pinch_in"):
            return
        self._u2_root_object().pinch_in(percent=percent, steps=steps)

    def pinch_out(self, percent=50, steps=20):
        """
        双指张开（放大）
        :param percent: 缩放幅度 1~100
        :param steps: 步数，越大越平滑
        """
        if not self._require_u2("pinch_out"):
            return
        self._u2_root_object().pinch_out(percent=percent, steps=steps)

    def zoom(self, zoom_in=True, percent=50, steps=20):
        """
        统一缩放入口
        :param zoom_in: True 放大 / False 缩小
        """
        if zoom_in:
            self.pinch_out(percent=percent, steps=steps)
        else:
            self.pinch_in(percent=percent, steps=steps)

    def two_finger_gesture(self, start1, start2, end1, end2, duration=0.5):
        """
        通用双指手势（像素坐标）。
        u2 3.x server 端已移除 gesture RPC（真机 -32601 method not found），
        改为从起止点向量推导：双指连线收拢 → pinch_in，撑开 → pinch_out。
        垂直平移等非缩放双指轨迹无法用本方法表达（server 能力限制）。
        :param start1: (x, y) 手指1起点
        :param start2: (x, y) 手指2起点
        :param end1:   (x, y) 手指1终点
        :param end2:   (x, y) 手指2终点
        :param duration: 手势时长（仅影响降级 swipe 时长）
        """
        if not self._require_u2("two_finger_gesture"):
            return
        def _dist_sq(a, b):
            return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
        start_span_sq = _dist_sq(start1, start2)
        end_span_sq = _dist_sq(end1, end2)
        steps = max(5, min(50, int(duration * 40)))
        if start_span_sq <= 0 or end_span_sq <= 0:
            logger.warning(f'two_finger_gesture: degenerate start/end points '
                           f'{start1} {start2} -> {end1} {end2}, skipped')
            return
        if end_span_sq < start_span_sq:
            # 双指收拢 → 捏合；percent 按跨度变化折算 1~100
            percent = max(1, min(100, int((1 - (end_span_sq / start_span_sq) ** 0.5) * 100)))
            self.pinch_in(percent=percent, steps=steps)
        else:
            percent = max(1, min(100, int(((end_span_sq / start_span_sq) ** 0.5 - 1) * 100)))
            self.pinch_out(percent=percent, steps=steps)

    # ==================================================================
    # 拖拽
    # ==================================================================
    def drag(self, from_x, from_y, to_x, to_y, duration=1.0, settle_time=0.15):
        """
        拖拽（终点短暂停留后再抬手，避免被识别为快速滑动）
        """
        self.swipe(from_x, from_y, to_x, to_y, duration, settle_time)

    # ==================================================================
    # 点击 / 长按 / 双击
    # ==================================================================
    def click(self, x=-1, y=-1, move_back=False, name=None, down_time=0.01, move=True, key=None):
        super().click(x, y, name=name)
        x = round(x)
        y = round(y)
        if isinstance(self.capture, NemuIpcCaptureMethod):
            self.capture.nemu_impl.click_nemu_ipc(x, y)
        else:
            self.device_manager.shell(f"input tap {x} {y}")

    def long_click(self, x, y, duration=1.0):
        """
        长按
        :param duration: 按住时长（秒）
        """
        x = round(x)
        y = round(y)
        if isinstance(self.capture, NemuIpcCaptureMethod):
            self.capture.nemu_impl.down(x, y)
            time.sleep(duration)
            self.capture.nemu_impl.up()
        elif self.use_u2:
            self.u2.long_click(x, y, duration)
        else:
            # ADB 兜底：起点=终点 + settle_time 实现长按
            self.device_manager.device.shell(
                f"input swipe {x} {y} {x} {y} {int(duration * 1000)}")

    def double_click(self, x, y, interval=0.1):
        """双击"""
        x = round(x)
        y = round(y)
        if self.use_u2:
            self.u2.double_click(x, y, interval)
        else:
            self.click(x, y)
            time.sleep(interval)
            self.click(x, y)

    # ==================================================================
    # 多点滑动（九宫格 / 自定义路径）
    # ==================================================================
    def swipe_points(self, points, duration=0.2):
        """
        多点连续滑动，可用于九宫格解锁、绘制路径等
        :param points: [(x1,y1), (x2,y2), ...] 像素坐标
        :param duration: 两点之间的滑动时长
        """
        if not self._require_u2("swipe_points"):
            return
        self.u2.swipe_points(points, duration)