import ctypes
import os
import subprocess
import time
from contextlib import contextmanager
from ctypes import c_int, c_uint, c_wchar_p, c_char_p, POINTER, c_ubyte
from pathlib import Path

import cv2
import numpy as np


@contextmanager
def _suppress_native_output():
    if os.name != "nt":
        yield
        return

    import sys

    sys.stdout.flush()
    sys.stderr.flush()

    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    null_fd = os.open(os.devnull, os.O_WRONLY)

    kernel32 = None
    saved_stdout_handle = None
    saved_stderr_handle = None

    try:
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)

        # 部分 native DLL 可能绕过 CRT 直接写 Windows 标准句柄，这里也一起重定向。
        try:
            import msvcrt

            kernel32 = ctypes.windll.kernel32
            saved_stdout_handle = kernel32.GetStdHandle(-11)
            saved_stderr_handle = kernel32.GetStdHandle(-12)
            null_handle = msvcrt.get_osfhandle(null_fd)
            kernel32.SetStdHandle(-11, null_handle)
            kernel32.SetStdHandle(-12, null_handle)
        except Exception:
            kernel32 = None

        yield

    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

        if kernel32 is not None:
            try:
                kernel32.SetStdHandle(-11, saved_stdout_handle)
                kernel32.SetStdHandle(-12, saved_stderr_handle)
            except Exception:
                pass

        try:
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)
            os.close(null_fd)


def load_config():
    config_data = {
        "adb_path": r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
        "adb_port": "127.0.0.1:16384",  # 16384 16416
        "screenshot_speed": 0.5,

        # MuMu 快速截图配置
        # mumu_path 是 MuMu 安装根目录，不是 adb.exe 所在目录
        "mumu_path": r"D:\Program Files\Netease\MuMu",
        "mumu_index": "auto",
        # auto: 优先 MuMu IPC，失败回退 ADB；adb: 只用 ADB；mumu: 只用 MuMu IPC
        "screenshot_method": "mumu",
    }

    try:
        with open("cfg.txt", "r", encoding="utf-8") as f:
            for line in f:
                if "=" not in line:
                    continue

                key, val = line.strip().split("=", 1)
                key = key.strip()
                val = val.strip()

                if key == "adb_port":
                    config_data["adb_port"] = val
                elif key == "adb_path":
                    config_data["adb_path"] = val
                elif key == "screenshot_speed":
                    config_data["screenshot_speed"] = float(val)
                elif key == "mumu_path":
                    config_data["mumu_path"] = val
                elif key == "mumu_index":
                    config_data["mumu_index"] = val
                elif key == "screenshot_method":
                    config_data["screenshot_method"] = val.lower()
    except Exception:
        pass

    return config_data


config = load_config()
adb_path = config["adb_path"]
adb_port = config["adb_port"]
screenshot_speed = config["screenshot_speed"]
_adb_connected_key = None


def _invalidate_adb_connection():
    """清除连接缓存；下一次使用时必须重新执行 adb connect。"""
    global _adb_connected_key
    _adb_connected_key = None


def connect_to_mumu(force=False):
    """连接当前 MuMu ADB；同一目标成功连接后直接复用。

    各任务仍可独立调用本函数，方便单文件运行。中控模式下所有任务共享
    本模块，因此重复调用不会再创建 ``adb connect`` / ``get-state``
    子进程。ADB 输入或截图真正失败时会清除缓存并强制重连。
    """
    global _adb_connected_key
    connection_key = (str(adb_path), str(adb_port))
    if not force and _adb_connected_key == connection_key:
        return True

    try:
        result = subprocess.run(
            [adb_path, "connect", adb_port],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            _invalidate_adb_connection()
            return False
        state = subprocess.run(
            [adb_path, "-s", adb_port, "get-state"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        connected = (
            state.returncode == 0
            and state.stdout.strip() == "device"
        )
        _adb_connected_key = connection_key if connected else None
        return connected
    except Exception:
        _invalidate_adb_connection()
        return False


def _infer_mumu_index(address: str) -> int:
    """
    从 MuMu ADB 地址推断多开编号。
    常见：
      127.0.0.1:16384 -> 0
      127.0.0.1:16416 -> 1
      emulator-5554    -> 0
      emulator-5556    -> 1
      127.0.0.1:5555  -> 0
      127.0.0.1:5557  -> 1
    """
    try:
        if address.startswith("emulator-"):
            port = int(address.split("-", 1)[1])
            if port >= 5554 and (port - 5554) % 2 == 0:
                return (port - 5554) // 2
            return 0

        port = int(address.rsplit(":", 1)[1])

        if port >= 16384:
            # MuMu 新版端口映射，参考 MAA 的推导逻辑
            k = (port - 16384) // 4
            return ((k & 7) << 5) | (k >> 3)

        if port == 7555:
            return 0

        if port >= 5555:
            return (port - 5555) // 2

    except Exception:
        pass

    return 0


def _get_mumu_index() -> int:
    """
    获取 MuMu 实例编号：
      - mumu_index=auto 时，根据 adb_port 自动推断
      - mumu_index=0/1/2... 时，使用手动指定值
    """
    value = str(config.get("mumu_index", "auto")).strip().lower()

    if value not in {"", "auto", "none", "null"}:
        try:
            return int(value)
        except ValueError:
            print(f"mumu_index 配置无效：{value}，改用 adb_port 自动推断")

    return _infer_mumu_index(adb_port)


class _MuMuIpcCapture:
    """
    MuMu external_renderer_ipc.dll 快速截图封装。
    失败时抛异常，由 take_screenshot() 决定是否回退 ADB。
    """

    def __init__(self, mumu_path: str, instance_index: int):
        self.mumu_path = Path(mumu_path)
        self.instance_index = instance_index
        # 固定使用 default，表示当前 MuMu 前台 tab。
        self.package_name = b"default"

        self.handle = 0
        self.width = 0
        self.height = 0
        self._dll_dir_handle = None

        self.dll_path = self._find_dll()
        # print("MuMu DLL:", self.dll_path)
        # print("MuMu path:", self.mumu_path)
        # print("MuMu index:", self.instance_index)

        # Python 3.8+ 在 Windows 上不会默认搜索 DLL 所在目录，手动加入依赖搜索路径
        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            self._dll_dir_handle = os.add_dll_directory(str(self.dll_path.parent))

        self.dll = ctypes.CDLL(str(self.dll_path))
        self._bind_functions()
        self._connect()
        self._init_size()

    def _find_dll(self) -> Path:
        candidates = [
            self.mumu_path / "nx_device" / "15.0" / "shell" / "sdk" / "external_renderer_ipc.dll",
            self.mumu_path / "nx_device" / "12.0" / "shell" / "sdk" / "external_renderer_ipc.dll",
            self.mumu_path / "shell" / "sdk" / "external_renderer_ipc.dll",
        ]

        for dll_path in candidates:
            if dll_path.exists():
                return dll_path

        raise FileNotFoundError(
            f"找不到 external_renderer_ipc.dll，请检查 mumu_path={self.mumu_path}"
        )

    def _bind_functions(self):
        self.dll.nemu_connect.argtypes = [c_wchar_p, c_int]
        self.dll.nemu_connect.restype = c_int

        self.dll.nemu_disconnect.argtypes = [c_int]
        self.dll.nemu_disconnect.restype = None

        self.dll.nemu_get_display_id.argtypes = [c_int, c_char_p, c_int]
        self.dll.nemu_get_display_id.restype = c_int

        self.dll.nemu_capture_display.argtypes = [
            c_int,
            c_uint,
            c_int,
            POINTER(c_int),
            POINTER(c_int),
            POINTER(c_ubyte),
        ]
        self.dll.nemu_capture_display.restype = c_int

    def _connect(self):
        with _suppress_native_output():
            self.handle = self.dll.nemu_connect(str(self.mumu_path), self.instance_index)
        if self.handle <= 0:
            raise RuntimeError(
                f"nemu_connect 失败：path={self.mumu_path}, index={self.instance_index}"
            )

    def _get_display_id(self) -> int:
        display_id = self.dll.nemu_get_display_id(self.handle, self.package_name, 0)
        if display_id < 0:
            raise RuntimeError(
                f"nemu_get_display_id 失败：package={self.package_name.decode('utf-8', errors='ignore')}"
            )
        return display_id

    def _init_size(self):
        width = c_int(0)
        height = c_int(0)
        display_id = self._get_display_id()

        ret = self.dll.nemu_capture_display(
            self.handle,
            c_uint(display_id),
            0,
            ctypes.byref(width),
            ctypes.byref(height),
            None,
        )

        if ret != 0 or width.value <= 0 or height.value <= 0:
            raise RuntimeError(f"MuMu 初始化截图尺寸失败：ret={ret}, size={width.value}x{height.value}")

        self.width = width.value
        self.height = height.value

    def capture_frame(self) -> np.ndarray:
        """
        通过 MuMu IPC 截图并直接返回 OpenCV BGR 图像数组，不写入磁盘。
        """
        width = c_int(self.width)
        height = c_int(self.height)
        buffer_size = self.width * self.height * 4
        buf = (c_ubyte * buffer_size)()

        display_id = self._get_display_id()
        ret = self.dll.nemu_capture_display(
            self.handle,
            c_uint(display_id),
            buffer_size,
            ctypes.byref(width),
            ctypes.byref(height),
            buf,
        )

        if ret != 0:
            raise RuntimeError(f"MuMu 截图失败：ret={ret}")

        rgba = np.frombuffer(buf, dtype=np.uint8).reshape((height.value, width.value, 4))

        # MuMu IPC 返回 RGBA，方向和 OpenCV 常用图像相反；按 MAA 逻辑转 BGR 并上下翻转。
        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        bgr = cv2.flip(bgr, 0)

        return bgr

    def capture_to_file(self, output_path: str = "screenshot.png") -> str:
        """
        兼容旧接口：需要保存截图时才写入磁盘。
        """
        frame = self.capture_frame()
        ok = cv2.imwrite(output_path, frame)
        if not ok:
            raise RuntimeError(f"写入截图失败：{output_path}")
        return output_path

    def close(self):
        if self.handle:
            try:
                self.dll.nemu_disconnect(self.handle)
            finally:
                self.handle = 0

        if self._dll_dir_handle is not None:
            try:
                self._dll_dir_handle.close()
            except Exception:
                pass
            self._dll_dir_handle = None


_mumu_capture = None
_mumu_capture_error = None
_last_screenshot_time = 0.0
_latest_screenshot_frame = None
_template_cache = {}
_missing_template_warned = set()


def reset_screenshot_backend():
    """
    清空缓存的 MuMu IPC 连接。切换多开、修改 cfg.txt、重启 MuMu 后可以手动调用。
    """
    global _mumu_capture, _mumu_capture_error, _last_screenshot_time, _latest_screenshot_frame

    if _mumu_capture is not None:
        try:
            _mumu_capture.close()
        except Exception:
            pass

    _mumu_capture = None
    _mumu_capture_error = None
    _last_screenshot_time = 0.0
    _latest_screenshot_frame = None


def configure_runtime_paths(
    adb_executable: str | None = None,
    mumu_root: str | None = None,
) -> None:
    """更新本次运行使用的 ADB 可执行文件和 MuMu 安装根目录。"""
    global adb_path

    changed = False
    if adb_executable is not None:
        resolved_adb = str(Path(adb_executable).expanduser())
        if not Path(resolved_adb).is_file():
            raise FileNotFoundError(f"ADB 文件不存在：{resolved_adb}")
        if resolved_adb != adb_path:
            adb_path = resolved_adb
            config["adb_path"] = resolved_adb
            changed = True

    if mumu_root is not None:
        resolved_mumu = str(Path(mumu_root).expanduser())
        if not Path(resolved_mumu).is_dir():
            raise NotADirectoryError(f"MuMu 目录不存在：{resolved_mumu}")
        if resolved_mumu != str(config.get("mumu_path", "")):
            config["mumu_path"] = resolved_mumu
            changed = True

    if changed:
        _invalidate_adb_connection()
        reset_screenshot_backend()


def configure_mumu_target(address: str, instance_index="auto") -> bool:
    """同时切换 ADB 输入目标与 MuMu IPC 截图实例。"""
    global adb_port

    target_address = str(address).strip()
    if not target_address:
        raise ValueError("MuMu ADB 地址不能为空")

    target_index = str(instance_index).strip()
    if not target_index:
        target_index = "auto"

    changed = (
        target_address != adb_port
        or str(config.get("mumu_index", "auto")) != target_index
    )
    adb_port = target_address
    config["adb_port"] = target_address
    config["mumu_index"] = target_index
    if changed:
        _invalidate_adb_connection()
        reset_screenshot_backend()
    return connect_to_mumu(force=changed)


def _get_mumu_capture():
    """
    懒加载并缓存 MuMu IPC 连接，避免每次截图都重新加载 DLL / 重新 connect。
    mumu_index 默认根据 adb_port 自动推断，不盲扫 0~7，避免 MuMu DLL 输出错误实例日志。
    """
    global _mumu_capture, _mumu_capture_error

    target_index = _get_mumu_index()

    if _mumu_capture is not None:
        # 如果当前缓存连接的 index 正确，直接复用
        if getattr(_mumu_capture, "instance_index", None) == target_index:
            return _mumu_capture

        # 如果 index 变了，关闭旧连接，重新初始化
        try:
            _mumu_capture.close()
        except Exception:
            pass

        _mumu_capture = None
        _mumu_capture_error = None

    try:
        _mumu_capture = _MuMuIpcCapture(
            mumu_path=config.get("mumu_path", r"D:\Program Files\Netease\MuMu"),
            instance_index=target_index,
        )
        _mumu_capture_error = None
        return _mumu_capture

    except Exception as e:
        _mumu_capture_error = str(e)
        raise


def _take_screenshot_by_adb() -> np.ndarray | None:
    """
    ADB 兜底截图。直接从 screencap 的 PNG 数据流解码成 OpenCV BGR 图像，不写入磁盘。
    失败时重连并重试一次。
    """
    cmd = [adb_path, "-s", adb_port, "exec-out", "screencap", "-p"]

    for attempt in range(2):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=12,
            )

            if result.stdout:
                raw = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
                if frame is not None:
                    return frame
                print("ADB截图失败：PNG 数据解码失败")

            else:
                print("ADB截图失败：stdout 为空")

        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
            print(f"ADB截图失败：{stderr}")

        except subprocess.TimeoutExpired:
            print("ADB截图超时")

        except Exception as e:
            print(f"ADB截图发生未知错误：{e}")

        if attempt == 0:
            print("尝试重新连接 MuMu ADB...")
            _invalidate_adb_connection()
            connect_to_mumu(force=True)

    return None


def take_screenshot() -> np.ndarray | None:
    """
      1. screenshot_method=auto：优先 MuMu IPC 快速截图，失败后回退 ADB
      2. screenshot_method=mumu：只使用 MuMu IPC
      3. screenshot_method=adb ：只使用 ADB
    如需保存截图，请调用 save_screenshot(output_path)。
    """
    global _mumu_capture, _mumu_capture_error, _last_screenshot_time, _latest_screenshot_frame

    # 可选限速：避免上层循环过快时疯狂截图
    now = time.perf_counter()
    min_interval = float(config.get("screenshot_speed", 0) or 0)
    if min_interval > 0 and _last_screenshot_time > 0:
        elapsed = now - _last_screenshot_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    method = str(config.get("screenshot_method", "auto")).lower()

    if method not in {"auto", "mumu", "adb"}:
        method = "auto"

    frame = None

    if method in {"auto", "mumu"}:
        try:
            cap = _get_mumu_capture()
            frame = cap.capture_frame()
            _last_screenshot_time = time.perf_counter()
            _latest_screenshot_frame = frame
            return frame

        except Exception as e:
            print(f"MuMu快速截图失败：{e}")
            # 截图过程中失败时，清空缓存，下次重新初始化
            if _mumu_capture is not None:
                try:
                    _mumu_capture.close()
                except Exception:
                    pass
                _mumu_capture = None
            # 不永久缓存失败状态，避免 MuMu 重启/切换实例后一直不重试
            _mumu_capture_error = None
            # mumu 模式不回退
            if method == "mumu":
                return None

    frame = _take_screenshot_by_adb()
    if frame is not None:
        _last_screenshot_time = time.perf_counter()
        _latest_screenshot_frame = frame

    return frame


def get_last_screenshot() -> np.ndarray | None:
    """
    返回最近一次 take_screenshot() 缓存的图像帧；不会重新截图。
    """
    return _latest_screenshot_frame


def save_screenshot(output_path: str = "screenshot.png", frame: np.ndarray | None = None) -> str | None:
    """
    显式保存截图到磁盘。
    - frame 为空：优先保存最近一帧；如果还没有最近一帧，则先截图。
    - frame 不为空：保存传入的 OpenCV BGR 图像数组。
    """
    if frame is None:
        frame = _latest_screenshot_frame
    if frame is None:
        frame = take_screenshot()
    if frame is None:
        print(f"保存截图失败：没有可保存的截图帧，output_path={output_path}")
        return None

    ok = cv2.imwrite(output_path, frame)
    if not ok:
        print(f"保存截图失败：{output_path}")
        return None

    return output_path


def _load_template(template_path: str) -> np.ndarray | None:
    """
    缓存模板图，避免每次匹配都反复 imread。
    """
    template = _template_cache.get(template_path)
    if template is not None:
        return template

    template = cv2.imread(template_path)
    if template is None:
        if template_path not in _missing_template_warned:
            print(f"[WARN] 模板图片读取失败：{template_path}")
            _missing_template_warned.add(template_path)
        return None

    _template_cache[template_path] = template
    return template


def crop_and_match(top_left, bottom_right, template_path, screenshot_path=None, frame: np.ndarray | None = None):
    """
    在内存截图上做模板匹配。
    默认使用最近一次 take_screenshot() 的缓存帧，不读取 screenshot.png。

    兼容旧调用：
      crop_and_match(..., screenshot_path="xxx.png") 或第 4 个位置参数为字符串时，仍可从磁盘读图。
    推荐新调用：
      frame = take_screenshot()
      crop_and_match(..., frame=frame)
    """
    if frame is None:
        # 向后兼容：如果第 4 个参数传了路径，则从磁盘读取该截图。
        if isinstance(screenshot_path, str) and screenshot_path:
            screenshot = cv2.imread(screenshot_path)
        else:
            screenshot = _latest_screenshot_frame
            if screenshot is None:
                screenshot = take_screenshot()
    else:
        screenshot = frame

    if screenshot is None:
        return None, None

    x1, y1 = top_left
    x2, y2 = bottom_right
    crop = screenshot[y1:y2, x1:x2]

    template = _load_template(template_path)
    if template is None:
        return None, None

    if crop.size == 0:
        return None, None

    crop_h, crop_w = crop.shape[:2]
    tmpl_h, tmpl_w = template.shape[:2]
    if tmpl_h > crop_h or tmpl_w > crop_w:
        return None, None

    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    h, w = template.shape[:2]

    match_left = x1 + max_loc[0]
    match_top = y1 + max_loc[1]
    match_right = match_left + w
    match_bottom = match_top + h

    return max_val, (match_left, match_top, match_right, match_bottom)


def _run_adb_device_command(arguments, timeout=8, label="ADB命令"):
    """执行设备命令；失败时强制重连一次并重试。"""
    command = [adb_path, "-s", adb_port, *arguments]
    last_error = ""
    for attempt in range(2):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return True
            last_error = (
                result.stderr.strip()
                or result.stdout.strip()
                or f"返回码 {result.returncode}"
            )
        except Exception as exc:
            last_error = str(exc)

        _invalidate_adb_connection()
        if attempt == 0 and connect_to_mumu(force=True):
            continue
        break

    print(f"{label}失败：{last_error or '无法连接设备'}")
    return False


def adb_click(x, y):
    return _run_adb_device_command(
        ["shell", "input", "tap", str(x), str(y)],
        timeout=8,
        label="ADB点击",
    )


def click_template_until_disappears(
    top_left,
    bottom_right,
    template_path,
    initial_rect,
    threshold=0.80,
    timeout=10.0,
    label="模板",
    click_callback=None,
    post_click_delay=0.5,
    still_visible_delay=1.0,
    log_callback=None,
):
    """
    点击已命中的模板，并在每次新截图中重新匹配。

    每次点击后先等待 post_click_delay，再截图确认。模板仍存在时按新
    匹配框再次点击；只有模板消失后才返回 True。
    这样上层不会在游戏尚未接受点击时提前进入下一步。
    """
    deadline = time.monotonic() + max(0.1, float(timeout))
    current_rect = initial_rect
    attempts = 0

    def emit(message):
        if log_callback is None:
            print(message)
        else:
            log_callback(message)

    while time.monotonic() < deadline:
        attempts += 1
        if click_callback is None:
            left, top, right, bottom = current_rect
            adb_click((left + right) // 2, (top + bottom) // 2)
        else:
            click_callback(current_rect)

        first_delay = max(0.0, float(post_click_delay))
        if first_delay > 0 and time.monotonic() < deadline:
            time.sleep(min(first_delay, max(0.0, deadline - time.monotonic())))

        frame = None
        while frame is None and time.monotonic() < deadline:
            frame = take_screenshot()
        if frame is None:
            break

        score, matched_rect = crop_and_match(
            top_left,
            bottom_right,
            template_path,
            frame=frame,
        )
        if score is None or matched_rect is None or score < threshold:
            emit(f"{label}模板已消失，点击已生效（共 {attempts} 次）")
            return True

        delay = max(0.0, float(still_visible_delay))
        if delay > 0 and time.monotonic() < deadline:
            emit(
                f"{label}点击后仍可见，匹配分数 {score:.3f}，"
                f"识别阈值 {threshold:.3f}，点击区域 {matched_rect}，"
                f"等待 {delay:g} 秒后重新截图确认"
            )
            time.sleep(min(delay, max(0.0, deadline - time.monotonic())))

            delayed_frame = None
            while delayed_frame is None and time.monotonic() < deadline:
                delayed_frame = take_screenshot()
            if delayed_frame is None:
                break
            delayed_score, delayed_rect = crop_and_match(
                top_left,
                bottom_right,
                template_path,
                frame=delayed_frame,
            )
            if (
                delayed_score is None
                or delayed_rect is None
                or delayed_score < threshold
            ):
                emit(f"{label}模板延迟后已消失，点击已生效（共 {attempts} 次）")
                return True
            emit(
                f"{label}延迟确认后仍可见，匹配分数 {delayed_score:.3f}，"
                f"识别阈值 {threshold:.3f}，点击区域 {delayed_rect}，"
                "继续点击"
            )
            current_rect = delayed_rect
        else:
            emit(
                f"{label}点击后仍可见，匹配分数 {score:.3f}，"
                f"识别阈值 {threshold:.3f}，点击区域 {matched_rect}，"
                "继续点击"
            )
            current_rect = matched_rect

    emit(f"[ERROR] {label}点击后未在 {timeout:g} 秒内消失")
    return False


def adb_swipe(start_x, start_y, end_x, end_y, duration_ms=800):
    """
    通过 ADB 执行可控时长的滑动手势。

    duration_ms 越大滑动越慢；账号列表使用约 1200ms，避免一次跳过整行。
    """
    duration_ms = max(100, int(duration_ms))
    return _run_adb_device_command(
        [
            "shell",
            "input",
            "swipe",
            str(int(start_x)),
            str(int(start_y)),
            str(int(end_x)),
            str(int(end_y)),
            str(duration_ms),
        ],
        timeout=max(8, duration_ms / 1000 + 3),
        label="ADB滑动",
    )


def adb_keyevent(keycode):
    """发送 Android 键盘事件；例如 keycode=4 表示返回键。"""
    return _run_adb_device_command(
        ["shell", "input", "keyevent", str(int(keycode))],
        timeout=8,
        label="ADB按键事件",
    )


def adb_back():
    """发送 Android 返回键。"""
    return adb_keyevent(4)


if __name__ == '__main__':
    connect_to_mumu()
    frame = take_screenshot()
    # print('take_screenshot frame:', None if frame is None else frame.shape)
    # 需要保存时再调用：
    save_screenshot("screenshot.png", frame)
